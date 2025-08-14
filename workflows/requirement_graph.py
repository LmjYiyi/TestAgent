import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import re
import json
from enum import Enum
from typing import TypedDict, Optional, Literal, Dict, List
from langgraph.graph import StateGraph, END
from langchain_chroma import Chroma
from models.dquestion import get_llm, get_embedding


# ======================
# 类型定义
# ======================
class ChangeType(str, Enum):
    LOGIC_ONLY = "纯逻辑变更"
    DICT_CHANGE = "逻辑变更+字典值变更"
    FIELD_ADD1 = "逻辑变更+字段新增(必输字段)"
    FIELD_ADD2 = "逻辑变更+字段新增(选输字段)"


class WorkflowState(TypedDict):
    file_path: str
    document_content: Optional[str]
    change_info: Optional[Dict]
    test_scenarios: Optional[List[Dict]]
    error_message: Optional[str]
    current_step: str
    result_message: Optional[str]


# ======================
# 共享工具函数
# ======================
def _call_RAG(change_info: Dict) -> List[Dict]:
    """查询向量数据库获取相关场景"""
    persist_path = "../db/siliconflow_vector_db"
    vectorstore = Chroma(
        persist_directory=persist_path,
        embedding_function=get_embedding()
    )

    retriever = vectorstore.as_retriever(
        search_kwargs={
            "filter": {
                "$and": [
                    {"接口中文名": {"$eq": change_info["interface_name"]}},
                    {"类型": {"$eq": "接口场景"}}
                ]
            },
            'k': 7
        }
    )

    if change_info['change_type'] == ChangeType.FIELD_ADD1.value:
        return retriever.invoke("步骤")
    return retriever.invoke(change_info.get("logic_changes", ""))


def extract_steps(content: str) -> List[str]:
    """从内容中提取步骤列表"""
    if not content:
        return []

    try:
        steps_part = re.split(r'步骤：\s*', content, flags=re.IGNORECASE)[-1]
        steps_part = re.split(r'\n\s*#{1,3}\s+|\n---', steps_part)[0]
        steps = re.findall(r'\d+\.\s*(.+?)\s*$', steps_part, flags=re.MULTILINE)
        return [step.strip() for step in steps if step.strip()]
    except Exception:
        return []


def _extract_first_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```.*?\n", "", text, flags=re.DOTALL)
        text = re.sub(r"\n```$", "", text).strip()
    try:
        json.loads(text)
        return text
    except Exception:
        m = re.search(r'(\{.*\}|\[.*\])', text, flags=re.S)
        if not m:
            raise ValueError("未找到可解析的 JSON 片段")
        return m.group(1)


# ======================
# 节点函数
# ======================
def read_document(state: WorkflowState) -> WorkflowState:
    """节点：读取文档内容"""
    try:
        with open(state["file_path"], "r", encoding="utf-8") as f:
            content = f.read()
            state["document_content"] = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
        state["current_step"] = "document_read"
    except Exception as e:
        state["error_message"] = f"文档读取失败: {str(e)}"
    return state


def extract_change_info(state: WorkflowState) -> WorkflowState:
    """节点：提取变更信息"""
    if not state.get("document_content"):
        state["error_message"] = "无文档内容可供分析"
        return state

    llm = get_llm()
    doc_content = state['document_content']
    prompt = f"""请严格按以下JSON格式从文档中提取变更信息:
    文档内容:
    {doc_content}

    输出要求:
    1. 变更类型必须为:{"/".join(e.value for e in ChangeType)}，必须为列表里的一种，且按原内容格式，不要自己编或者换说法，
       正确示例:"change_type":"逻辑变更+字段新增(必输字段)"    必须严格按照原始值来； 
       错误示例: "change_type": "字段新增(必输字段)/纯逻辑变更"， 自己根据意思重新编辑是错误的
    2. 字段路径必须完整(如request.body.user_info)
    3. 字典值变更需包含参数名和具体值变化
    4. 仅返回纯JSON字符串，不包含任何Markdown格式(如```json、注释、文字说明)。

    输出格式:
    {{
        "requirement_id": "需求ID",
        "interface_name": "接口中文名称(直接名字，不要带接口后缀)",
        "change_type": "变更类型(严格按照原始值来)",
        "field_changes": {{
            "added": [{{"name": "字段名", "required": true, "description": "说明"}}],
            "deleted": ["字段路径"],
            "modified": [{{"name": "字段名", "old": "原属性", "new": "新属性"}}]
        }},
        "dict_changes": [{{"param": "参数名", "changes": "值变化描述"}}],
        "logic_changes": "逻辑变更描述"
    }}"""
    try:
        response = llm.invoke(prompt)
        content = _extract_first_json(response.content if hasattr(response, "content") else str(response))
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```.*?\n", "", content, flags=re.DOTALL)
            content = re.sub(r"\n```$", "", content)
            content = content.strip()  # 去除首尾空白
        state["change_info"] = json.loads(content)
        # print(content)
        state["current_step"] = "info_extracted"
    except Exception as e:
        state["error_message"] = f"变更信息提取失败: {str(e)}"
    return state


def route_by_change_type(state: WorkflowState) -> Literal["logic", "dict", "field1", "field2", "handle_error"]:
    if state.get("error_message"):
        return "handle_error"

    ct = (state.get("change_info") or {}).get("change_type", "")
    # print(ct)
    if ct == ChangeType.LOGIC_ONLY.value:
        return "logic"
    elif ct == ChangeType.DICT_CHANGE.value:
        return "dict"
    elif ct == ChangeType.FIELD_ADD1.value:
        return "field1"
    elif ct == ChangeType.FIELD_ADD2.value:
        return "field2"
    return "handle_error"


def handle_logic_change(state: WorkflowState) -> WorkflowState:
    """节点：处理纯逻辑变更"""
    llm = get_llm()
    change_info = state["change_info"]
    docs = _call_RAG(change_info)
    if not docs:
        print(f"未找到匹配文档")
        state["error_message"] = "知识库未命中相关场景，请检查接口中文名或向量库内容"
        return state
    prompt = f"""请根据以下信息判断总结本次纯逻辑变更需求波及到的接口场景信息:
    本次变更信息:
    {change_info}
    RAG知识库查询到的本次变更接口下的所有场景信息:
    {docs}

    要求:
    1. 根据知识库中查询到的接口下的所有场景信息，为本次纯逻辑变更生成波及接口场景信息列表
    2. 根据本次的逻辑变动，筛选出波及影响到的接口场景信息

    输出格式:
    [
        {{
            "interface_name": "本次变更的接口中文名",
            "scene_name": "本次变更波及的场景名",
            "description":"判断本场景被波及到的依据"
        }}
        {{
            "interface_name": "本次变更的接口中文名",
            "scene_name": "本次变更波及的场景名",
            "description":"判断本场景被波及到的依据"
        }}
        ....列举所有筛选出的波及接口场景列表
    ]
    """
    try:
        response = llm.invoke(prompt)
        content = _extract_first_json(response.content if hasattr(response, "content") else str(response))
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:].strip("` \n")

        scenarios = json.loads(content)
        state["test_scenarios"] = [{
            '接口名': s['interface_name'],
            '场景名': s['scene_name'],
            '判断依据': s['description']
        } for s in scenarios]
        state["current_step"] = "logic_processed"
        state['result_message'] = "本次变更需求为纯逻辑变更，不影响报文结构，波及的接口场景如下:"
    except Exception as e:
        state["error_message"] = f"逻辑变更处理失败: {str(e)}"
    return state


def handle_dict_change(state: WorkflowState) -> WorkflowState:
    """节点：处理字典值变更"""
    llm = get_llm()
    change_info = state["change_info"]
    docs = _call_RAG(change_info)
    if not docs:
        print(f"未找到匹配文档")
    prompt = f"""请根据以下信息为字典值变更需求(意味着新增场景)设计测试方案:
    本次变更信息:
    {change_info}
    RAG知识库查询到的类似接口场景信息:
    {docs}

    要求:
    1. 为本次字典值新增变更设计新的测试要点(四个步骤)
    2. 包含正常值和边界值测试
    3. 说明预期结果
    4. 从匹配到的知识库信息里查找是否有类似的接口场景，可以参考里面的操作步骤
    5. 如果没有匹配到类似的接口场景，即本次变更完全是全新的场景，则需要你自己根据经验设计一下测试要点

    输出格式:
    {{
        "interface_name": "本次变更的接口中文名",
        "scene_name": "本次变更新增的场景描述",
        "related_scene": "参考的知识库类似接口场景，若没有，则为空",
        "steps": "生成的测试要点:["步骤1", "步骤2"]",
        "expected": "预期结果",
    }}"""
    try:
        response = llm.invoke(prompt)
        content = _extract_first_json(response.content if hasattr(response, "content") else str(response))
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:].strip("` \n")

        data = json.loads(content)
        state["test_scenarios"] = [{
            "接口名": data.get("interface_name", ""),
            "新增场景名": data.get("scene_name", ""),
            "相关场景": data.get("related_scene", ""),
            "测试步骤": data.get("steps", []),
            "预期结果": data.get("expected", "")
        }]
        state["current_step"] = "dict_processed"
        state['result_message'] = "本次需求变更为字典值新增(新场景)，结合知识库为本次变更需求生成的测试要点如下:"
    except Exception as e:
        state["error_message"] = f"字典变更处理失败: {str(e)}"
    return state


def handle_field1_change(state: WorkflowState) -> WorkflowState:
    """节点：处理必输字段新增"""
    try:
        docs = _call_RAG(state["change_info"])
        if not docs:
            print(f"未找到匹配文档")
            state["error_message"] = "知识库未命中相关场景，请检查接口中文名或向量库内容"
            return state
        state["test_scenarios"] = [{
            '接口名': doc.metadata['接口中文名'],
            '场景名': doc.metadata['场景名'],
            '测试步骤': extract_steps(doc.page_content)
        } for doc in docs]
        state["current_step"] = "field1_processed"
        state['result_message'] = "本次需求变更为新增必输字段，影响接口全场景和原始报文结构，波及的接口场景以及测试要点如下："
    except Exception as e:
        state["error_message"] = f"必输字段处理失败: {str(e)}"
    return state


def handle_field2_change(state: WorkflowState) -> WorkflowState:
    """节点：处理选输字段新增"""
    llm = get_llm()
    change_info = state["change_info"]
    docs = _call_RAG(change_info)
    if not docs:
        print(f"未找到匹配文档")
        state["error_message"] = "知识库未命中相关场景，请检查接口中文名或向量库内容"
        return state

    prompt = f"""请根据以下信息判断总结本次新增选输字段变更需求波及到的接口场景信息:
    本次变更信息:
    {change_info}
    RAG知识库查询到的本次变更接口下的所有场景信息:
    {docs}

    要求:
    1. 根据知识库中查询到的接口下的所有场景信息，为本次新增选输字段变更生成波及的接口场景信息列表
    3. 根据本次的逻辑变动，筛选出波及影响到的接口场景信息(包含测试步骤)

    输出格式:
    [
        {{
            "interface_name": "本次变更的接口中文名",
            "scene_name": "本次变更波及的场景名",
            "steps": "本场景的测试步骤(完全按原始知识库内容来，不要去总结重编)",
            "description":"判断本场景被波及到的依据"
        }}
        {{
            "interface_name": "本次变更的接口中文名",
            "scene_name": "本次变更波及的场景名",
            "steps": "本场景的测试步骤(完全按原始知识库内容来，不要去总结重编)",
            "description":"判断本场景被波及到的依据"
        }}
        ....列举所有筛选出的波及接口场景列表
    ]
    """
    try:
        response = llm.invoke(prompt)
        content = _extract_first_json(response.content if hasattr(response, "content") else str(response))
        content = content.strip()
        print(content)
        if content.startswith("```json"):
            content = content[7:].strip("` \n")

        datas = json.loads(content)
        state["test_scenarios"] = [{
            '接口名': data['interface_name'],
            '场景名': data['scene_name'],
            '测试步骤': data['steps'],
            '判断依据': data['description']
        } for data in datas]
        state["current_step"] = "field2_processed"
        state['result_message'] = "本次需求变更为新增选输字段，可能影响报文结构，波及的接口场景以及测试要点如下:"
    except Exception as e:
        state["error_message"] = f"选输字段处理失败: {str(e)}"
    return state


def handle_error(state: WorkflowState) -> WorkflowState:
    """节点：错误处理"""
    print(f"流程在步骤 [{state.get('current_step', 'unknown')}] 出错: {state.get('error_message', '未知错误')}")
    return state


# ======================
# 工作流构建
# ======================
def build_test_scenario_workflow():
    workflow = StateGraph(WorkflowState)

    # 添加节点
    workflow.add_node("read", read_document)
    workflow.add_node("extract", extract_change_info)
    workflow.add_node("logic", handle_logic_change)
    workflow.add_node("dict", handle_dict_change)
    workflow.add_node("field1", handle_field1_change)
    workflow.add_node("field2", handle_field2_change)
    workflow.add_node("handle_error", handle_error)

    # 设置边关系
    workflow.add_edge("read", "extract")
    # ✅ 直接从 extract 做条件分支
    workflow.add_conditional_edges(
        "extract",                      # ← 这里从 extract 分流
        route_by_change_type,           # 返回 "logic"/"dict"/"field1"/"field2"/"handle_error"
        {
            "logic": "logic",
            "dict": "dict",
            "field1": "field1",
            "field2": "field2",
            "handle_error": "handle_error"
        }
    )

    # 连接终节点
    workflow.add_edge("logic", END)
    workflow.add_edge("dict", END)
    workflow.add_edge("field1", END)
    workflow.add_edge("field2", END)
    workflow.add_edge("handle_error", END)

    workflow.set_entry_point("read")
    return workflow.compile()


# ======================
# 主执行流程
# ======================
if __name__ == "__main__":
    # 初始化工作流
    app = build_test_scenario_workflow()

    # 准备输入
    inputs = {
        "file_path": "docs/requirements/1.纯逻辑变更.md",  # 1.纯逻辑变更，2.字典值变更，3.新增必输字段，4.新增选输字段
        "document_content": None,
        "change_info": None,
        "test_scenarios": None,
        "error_message": None,
        "current_step": "start",
        "result_message": None
    }

    # 执行工作流
    print("开始执行需求分析测试场景工作流...")
    for output in app.stream(inputs):
        for node, state_snapshot in output.items():
            # print(f"\n[{node.upper()}] 步骤完成")
            if state_snapshot.get("test_scenarios") is not None:
                print(state_snapshot['result_message'])
                print(json.dumps(state_snapshot["test_scenarios"], indent=2, ensure_ascii=False))
            if state_snapshot.get("error_message"):
                print(f"错误信息: {state_snapshot['error_message']}")

    print("\n工作流执行完毕")
