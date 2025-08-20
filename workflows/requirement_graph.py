import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import re
import json
import asyncio
from enum import Enum
from typing import TypedDict, Optional, Literal, Dict, List, Annotated, Sequence
from langgraph.graph import StateGraph, END
from langchain_chroma import Chroma
from langchain_core.messages import SystemMessage, BaseMessage, HumanMessage, AIMessage
from langgraph.graph.message import add_messages
from langgraph.checkpoint.base import BaseCheckpointSaver
from models.dquestion import get_llm, get_embedding
from utils import logger
from utils.db_utils import DatabaseManager
from tools.rag_tools import query_scene_list, query_interface_details
from agents.mcp_agent import get_mcp_agent

from tools.logic_validator import validate_step_logic
from prompts.requirement_prompts import (
    EXTRACT_CHANGE_INFO_PROMPT,
    LOGIC_CHANGE_PROMPT,
    DICT_CHANGE_PROMPT,
    FIELD1_CHANGE_PROMPT,
    FIELD2_CHANGE_PROMPT
)
from prompts.workflow_prompts import STEP_1_PROMPT, STEP_2_PROMPT, STEP_3_PROMPT, STEP_4_PROMPT


# ======================
# 类型定义
# ======================
class ChangeType(str, Enum):
    LOGIC_ONLY = "纯逻辑变更"
    DICT_CHANGE = "逻辑变更+字典值变更"
    FIELD_ADD1 = "逻辑变更+字段新增(必输字段)"
    FIELD_ADD2 = "逻辑变更+字段新增(选输字段)"


class RequirementState(TypedDict):
    user_input: str
    auto_continue: bool
    current_stage: Literal["analyze_requirement", "route_change_type", "process_change", "select_scenario", "execute_test"]
    document_content: Optional[str]
    change_info: Optional[Dict]
    test_scenarios: Optional[List[Dict]]
    selected_scenario: Optional[Dict]
    error_message: Optional[str]
    result_message: Optional[str]
    output: str
    pending_action: Optional[str]
    user_confirmed: Optional[bool]
    messages: Annotated[Sequence[BaseMessage], add_messages]


# ======================
# 共享工具函数
# ======================
# def _call_RAG(change_info: Dict) -> List[Dict]:
#     """查询向量数据库获取相关场景"""
#     persist_path = "../db/siliconflow_vector_db"
#     vectorstore = Chroma(
#         persist_directory=persist_path,
#         embedding_function=get_embedding()
#     )
#
#     retriever = vectorstore.as_retriever(
#         search_kwargs={
#             "filter": {
#                 "$and": [
#                     {"接口中文名": {"$eq": change_info["interface_name"]}},
#                     {"类型": {"$eq": "接口场景"}}
#                 ]
#             },
#             'k': 7
#         }
#     )
#
#     if change_info['change_type'] == ChangeType.FIELD_ADD1.value:
#         return retriever.invoke("步骤")
#     return retriever.invoke(change_info.get("logic_changes", ""))
def _call_RAG(change_info: Dict) -> List[Dict]:
    """查询向量数据库获取相关场景（纯过滤查询，不计算相似度）"""
    persist_path = "db/siliconflow_vector_db"
    vectorstore = Chroma(
        persist_directory=persist_path,
        embedding_function=get_embedding()  # 即使不用，也需要保留
    )

    # 纯过滤查询：直接按 metadata 筛选文档
    results = vectorstore.get(
        where={
            "$and": [
                {"接口中文名": {"$eq": change_info["interface_name"]}},
                {"类型": {"$eq": "接口场景"}}
            ]
        },
        limit=7  # 限制返回数量
    )
    #print(results)
    return results


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


def create_initial_requirement_state(document_content: str) -> RequirementState:
    """为新需求分析创建初始状态"""
    return RequirementState(
        user_input="",
        auto_continue=True,
        current_stage="analyze_requirement",
        document_content=document_content,
        change_info=None,
        test_scenarios=None,
        selected_scenario=None,
        error_message=None,
        result_message=None,
        output="",
        pending_action=None,
        user_confirmed=None,
        messages=[HumanMessage(content=f"开始分析需求文档")]
    )

# ======================
# 节点函数
# ======================
async def analyze_requirement(state: RequirementState) -> RequirementState:
    """节点：分析需求文档并提取变更信息"""
    logger.info("开始分析需求文档...")
    
    if not state.get("document_content"):
        output = "错误：无文档内容可供分析"
        return {
            **state,
            "error_message": "无文档内容可供分析", 
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }

    llm = get_llm()
    doc_content = state['document_content']
    prompt = EXTRACT_CHANGE_INFO_PROMPT.format(
        doc_content=doc_content,
        change_types="/".join(e.value for e in ChangeType)
    )
    
    try:
        response = llm.invoke(prompt)
        content = _extract_first_json(response.content if hasattr(response, "content") else str(response))
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```.*?\n", "", content, flags=re.DOTALL)
            content = re.sub(r"\n```$", "", content)
            content = content.strip()
            
        change_info = json.loads(content)
        logger.info(f"分析完成，变更类型: {change_info.get('change_type')}")
        
        output = f"✅ 需求文档分析完成\n\n📋 **分析结果**:\n" \
                f"- **接口名称**: {change_info.get('interface_name', 'N/A')}\n" \
                f"- **变更类型**: {change_info.get('change_type', 'N/A')}\n" \
                f"- **变更描述**: {change_info.get('logic_changes', 'N/A')}\n\n" \
                f"正在生成测试场景..."
        
        return {
            **state,
            "change_info": change_info,
            "current_stage": "process_change",
            "auto_continue": True,
            "output": output,
            "messages": [AIMessage(content=output)]
        }
        
    except Exception as e:
        logger.error(f"需求分析失败: {str(e)}")
        output = f"❌ 需求分析失败: {str(e)}"
        return {
            **state,
            "error_message": f"变更信息提取失败: {str(e)}",
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }


async def process_change(state: RequirementState) -> RequirementState:
    """节点：根据变更类型处理并生成测试场景"""
    logger.info("开始处理变更需求...")
    
    if state.get("error_message"):
        return state
        
    change_info = state.get("change_info")
    if not change_info:
        output = "错误：缺少变更信息"
        return {
            **state,
            "error_message": "缺少变更信息",
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }
    
    ct = change_info.get("change_type", "")
    logger.info(f"变更类型: {ct}")
    
    try:
        if ct == ChangeType.LOGIC_ONLY.value:
            return await handle_logic_change(state)
        elif ct == ChangeType.DICT_CHANGE.value:
            return await handle_dict_change(state)
        elif ct == ChangeType.FIELD_ADD1.value:
            return await handle_field1_change(state)
        elif ct == ChangeType.FIELD_ADD2.value:
            return await handle_field2_change(state)
        else:
            output = f"❌ 不支持的变更类型: {ct}"
            return {
                **state,
                "error_message": f"不支持的变更类型: {ct}",
                "output": output,
                "auto_continue": False,
                "messages": [AIMessage(content=output)]
            }
    except Exception as e:
        logger.error(f"处理变更失败: {str(e)}")
        output = f"❌ 处理变更失败: {str(e)}"
        return {
            **state,
            "error_message": f"处理变更失败: {str(e)}",
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }


async def handle_logic_change(state: RequirementState) -> RequirementState:
    """节点：处理纯逻辑变更"""
    logger.info("处理纯逻辑变更...")
    llm = get_llm()
    change_info = state["change_info"]
    docs = _call_RAG(change_info)
    if not docs:
        logger.warning("未找到匹配文档")
        output = "❌ 知识库未命中相关场景，请检查接口中文名或向量库内容"
        return {
            **state,
            "error_message": "知识库未命中相关场景，请检查接口中文名或向量库内容",
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }
    
    # 提取原始接口场景的测试步骤
    original_scenarios = []
    if docs and docs.get("documents") and docs.get("metadatas"):
        for doc_content, doc_metadata in zip(docs["documents"], docs["metadatas"]):
            scene_steps = extract_steps(doc_content)
            if scene_steps:
                original_scenarios.append({
                    "场景名": doc_metadata.get("场景名", ""),
                    "原始测试步骤": scene_steps
                })
    
    prompt = LOGIC_CHANGE_PROMPT.format(
        change_info=change_info,
        original_scenarios=original_scenarios,
        docs=docs
    )
    try:
        response = llm.invoke(prompt)
        content = _extract_first_json(response.content if hasattr(response, "content") else str(response))
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:].strip("` \n")

        scenarios = json.loads(content)
        test_scenarios = [{
            '接口名': s['interface_name'],
            '场景名': s['scene_name'],
            '原始步骤': s.get('original_steps', ''),
            '测试步骤': s.get('updated_test_steps', []),
            '判断依据': s['description']
        } for s in scenarios]
        
        result_message = "本次变更需求为纯逻辑变更，不影响报文结构，波及以下场景并生成了相应的测试场景："
        
        # 构建场景列表输出
        scenario_list = "\n".join([f"{i+1}. {s['场景名']}" for i, s in enumerate(test_scenarios)])
        output = f"✅ {result_message}\n\n📝 **波及场景** ({len(test_scenarios)}个):\n{scenario_list}\n\n请选择要执行的场景编号，或输入'全部'执行所有场景："
        
        return {
            **state,
            "test_scenarios": test_scenarios,
            "result_message": result_message,
            "current_stage": "select_scenario",
            "auto_continue": False,
            "output": output,
            "messages": [AIMessage(content=output)]
        }
    except Exception as e:
        logger.error(f"逻辑变更处理失败: {str(e)}")
        output = f"❌ 逻辑变更处理失败: {str(e)}"
        return {
            **state,
            "error_message": f"逻辑变更处理失败: {str(e)}",
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }


async def handle_dict_change(state: RequirementState) -> RequirementState:
    """节点：处理字典值变更"""
    logger.info("处理字典值变更...")
    llm = get_llm()
    change_info = state["change_info"]
    docs = _call_RAG(change_info)
    if not docs:
        logger.warning("未找到匹配文档")
    
    # 提取原始接口场景的测试步骤作为参考
    original_test_steps = []
    if docs and docs.get("documents") and docs.get("metadatas"):
        for doc_content, doc_metadata in zip(docs["documents"], docs["metadatas"]):
            scene_steps = extract_steps(doc_content)
            if scene_steps:
                original_test_steps.append({
                    "场景名": doc_metadata.get("场景名", ""),
                    "测试步骤": scene_steps
                })
    
    prompt = DICT_CHANGE_PROMPT.format(
        change_info=change_info,
        original_test_steps=original_test_steps,
        docs=docs
    )
    try:
        response = llm.invoke(prompt)
        content = _extract_first_json(response.content if hasattr(response, "content") else str(response))
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:].strip("` \n")

        data = json.loads(content)
        
        # 按照四大步骤格式组织测试步骤
        test_steps = [
            f"步骤一：{data.get('step1', '')}",
            f"步骤二：{data.get('step2', '')}",
            f"步骤三：{data.get('step3', '')}",
            f"步骤四：{data.get('step4', '')}"
        ]
        
        test_scenarios = [{
            "接口名": data.get("interface_name", ""),
            "场景名": data.get("scene_name", ""),
            "相关场景": data.get("related_scene", ""),
            "测试步骤": test_steps,
            "预期结果": data.get("expected", "")
        }]
        
        result_message = "本次需求变更为字典值新增，生成了新场景："
        
        # 构建场景输出
        scenario_info = f"1. {data.get('scene_name', 'N/A')}"
        output = f"✅ {result_message}\n\n📝 **新增场景**:\n{scenario_info}\n\n请输入场景名称或'继续'执行该场景："
        
        return {
            **state,
            "test_scenarios": test_scenarios,
            "result_message": result_message,
            "current_stage": "select_scenario",
            "auto_continue": False,
            "output": output,
            "messages": [AIMessage(content=output)]
        }
    except Exception as e:
        logger.error(f"字典变更处理失败: {str(e)}")
        output = f"❌ 字典变更处理失败: {str(e)}"
        return {
            **state,
            "error_message": f"字典变更处理失败: {str(e)}",
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }


async def handle_field1_change(state: RequirementState) -> RequirementState:
    """节点：处理必输字段新增"""
    logger.info("处理必输字段新增...")
    try:
        llm = get_llm()
        change_info = state["change_info"]
        docs = _call_RAG(change_info)
        if not docs:
            logger.warning("未找到匹配文档")
            output = "❌ 知识库未命中相关场景，请检查接口中文名或向量库内容"
            return {
                **state,
                "error_message": "知识库未命中相关场景，请检查接口中文名或向量库内容",
                "output": output,
                "auto_continue": False,
                "messages": [AIMessage(content=output)]
            }
        
        # 提取原始接口场景的测试步骤
        original_scenarios = []
        if docs and docs.get("documents") and docs.get("metadatas"):
            for doc_content, doc_metadata in zip(docs["documents"], docs["metadatas"]):
                scene_steps = extract_steps(doc_content)
                if scene_steps:
                    original_scenarios.append({
                        "场景名": doc_metadata.get("场景名", ""),
                        "原始测试步骤": scene_steps
                    })
        
        prompt = FIELD1_CHANGE_PROMPT.format(
            change_info=change_info,
            original_scenarios=original_scenarios
        )
        
        response = llm.invoke(prompt)
        content = _extract_first_json(response.content if hasattr(response, "content") else str(response))
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:].strip("` \n")
        
        scenarios = json.loads(content)
        test_scenarios = [{
            '接口名': s["interface_name"],
            '场景名': s["scene_name"],
            '原始步骤': s.get('original_steps', ''),
            '测试步骤': s.get('updated_test_steps', []),
            '调整说明': s.get('description', '')
        } for s in scenarios]
        
        result_message = "本次需求变更为新增必输字段，影响接口全场景和原始报文结构，波及以下场景并生成了相应的测试场景："
        
        # 构建场景列表输出
        scenario_list = "\n".join([f"{i+1}. {s['场景名']}" for i, s in enumerate(test_scenarios)])
        output = f"✅ {result_message}\n\n📝 **波及场景** ({len(test_scenarios)}个):\n{scenario_list}\n\n请选择要执行的场景编号，或输入'全部'执行所有场景："
        
        return {
            **state,
            "test_scenarios": test_scenarios,
            "result_message": result_message,
            "current_stage": "select_scenario",
            "auto_continue": False,
            "output": output,
            "messages": [AIMessage(content=output)]
        }
    except Exception as e:
        logger.error(f"必输字段处理失败: {str(e)}")
        output = f"❌ 必输字段处理失败: {str(e)}"
        return {
            **state,
            "error_message": f"必输字段处理失败: {str(e)}",
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }


async def handle_field2_change(state: RequirementState) -> RequirementState:
    """节点：处理选输字段新增"""
    logger.info("处理选输字段新增...")
    llm = get_llm()
    change_info = state["change_info"]
    docs = _call_RAG(change_info)
    if not docs:
        logger.warning("未找到匹配文档")
        output = "❌ 知识库未命中相关场景，请检查接口中文名或向量库内容"
        return {
            **state,
            "error_message": "知识库未命中相关场景，请检查接口中文名或向量库内容",
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }

    # 提取原始接口场景的测试步骤
    original_scenarios = []
    if docs and docs.get("documents") and docs.get("metadatas"):
        for doc_content, doc_metadata in zip(docs["documents"], docs["metadatas"]):
            scene_steps = extract_steps(doc_content)
            if scene_steps:
                original_scenarios.append({
                    "场景名": doc_metadata.get("场景名", ""),
                    "原始测试步骤": scene_steps
                })

    prompt = FIELD2_CHANGE_PROMPT.format(
        change_info=change_info,
        original_scenarios=original_scenarios,
        docs=docs
    )
    try:
        response = llm.invoke(prompt)
        content = _extract_first_json(response.content if hasattr(response, "content") else str(response))
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:].strip("` \n")

        datas = json.loads(content)
        test_scenarios = [{
            '接口名': data['interface_name'],
            '场景名': data['scene_name'],
            '原始步骤': data.get('original_steps', ''),
            '测试步骤': data.get('updated_test_steps', []),
            '判断依据': data['description']
        } for data in datas]
        
        result_message = "本次需求变更为新增选输字段，可能影响报文结构，波及以下场景并生成了相应的测试场景："
        
        # 构建场景列表输出
        scenario_list = "\n".join([f"{i+1}. {s['场景名']}" for i, s in enumerate(test_scenarios)])
        output = f"✅ {result_message}\n\n📝 **波及场景** ({len(test_scenarios)}个):\n{scenario_list}\n\n请选择要执行的场景编号，或输入'全部'执行所有场景："
        
        return {
            **state,
            "test_scenarios": test_scenarios,
            "result_message": result_message,
            "current_stage": "select_scenario",
            "auto_continue": False,
            "output": output,
            "messages": [AIMessage(content=output)]
        }
    except Exception as e:
        logger.error(f"选输字段处理失败: {str(e)}")
        output = f"❌ 选输字段处理失败: {str(e)}"
        return {
            **state,
            "error_message": f"选输字段处理失败: {str(e)}",
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }


async def select_scenario(state: RequirementState) -> RequirementState:
    """节点：场景选择"""
    logger.info("等待用户选择测试场景...")
    
    user_input = state.get("user_input", "").strip()
    test_scenarios = state.get("test_scenarios", [])
    
    if not test_scenarios:
        output = "❌ 没有可用的测试场景"
        return {
            **state,
            "error_message": "没有可用的测试场景",
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }
    
    # 如果没有用户输入，暂停等待
    if not user_input:
        # 构建场景列表和测试步骤输出
        scenario_list = "\n".join([f"{i+1}. {s['场景名']}" for i, s in enumerate(test_scenarios)])
        
        # 显示测试步骤详情
        steps_details = "\n\n📋 **测试步骤详情**:\n"
        for i, scenario in enumerate(test_scenarios, 1):
            steps_details += f"\n**场景{i}: {scenario['场景名']}**\n"
            if isinstance(scenario.get('测试步骤'), list):
                for j, step in enumerate(scenario['测试步骤'], 1):
                    steps_details += f"  步骤{j}: {step}\n"
            else:
                steps_details += f"  步骤: {scenario.get('测试步骤', 'N/A')}\n"
            if scenario.get('判断依据'):
                steps_details += f"  判断依据: {scenario['判断依据']}\n"
        
        output = f"📝 **波及场景** ({len(test_scenarios)}个):\n{scenario_list}{steps_details}\n\n请选择要执行的场景编号，或输入'全部'执行所有场景："
        return {
            **state,
            "output": output,
            "auto_continue": False,  # 关键：设置为False，暂停等待用户输入
            "messages": [AIMessage(content=output)]
        }
    
    # 处理用户选择
    if user_input == "全部":
        # 选择所有场景，逐个执行
        output = f"✅ 已选择执行全部 {len(test_scenarios)} 个场景，开始执行测试..."
        selected_scenario = {
            "scenarios": test_scenarios,
            "current_index": 0,
            "total": len(test_scenarios),
            "mode": "all"
        }
    elif user_input == "继续":
        # 只有一个场景时直接执行
        output = f"✅ 开始执行测试场景：{test_scenarios[0].get('场景名', 'N/A')}"
        selected_scenario = {
            "scenarios": [test_scenarios[0]], 
            "current_index": 0,
            "total": 1,
            "mode": "single"
        }
    elif user_input.isdigit():
        # 选择特定场景编号
        idx = int(user_input) - 1
        if 0 <= idx < len(test_scenarios):
            selected_scenario_info = test_scenarios[idx]
            output = f"✅ 已选择场景：{selected_scenario_info.get('场景名', 'N/A')}，开始执行测试..."
            selected_scenario = {
                "scenarios": [selected_scenario_info],
                "current_index": 0, 
                "total": 1,
                "mode": "single"
            }
        else:
            output = f"❌ 输入的编号 {user_input} 超出范围，请输入 1-{len(test_scenarios)} 之间的数字"
            return {
                **state,
                "output": output,
                "auto_continue": False,
                "messages": [AIMessage(content=output)]
            }
    else:
        # 尝试通过场景名称匹配
        matched_scenarios = []
        for scenario in test_scenarios:
            scenario_name = scenario.get('场景名', '')
            if user_input in scenario_name or scenario_name in user_input:
                matched_scenarios.append(scenario)
        
        if len(matched_scenarios) == 1:
            # 找到唯一匹配的场景
            selected_scenario_info = matched_scenarios[0]
            output = f"✅ 已选择场景：{selected_scenario_info.get('场景名', 'N/A')}，开始执行测试..."
            selected_scenario = {
                "scenarios": [selected_scenario_info],
                "current_index": 0,
                "total": 1,
                "mode": "single"
            }
        elif len(matched_scenarios) > 1:
            # 多个匹配，列出供用户选择
            scenario_list = "\n".join([f"{i+1}. {s.get('场景名', 'N/A')}" for i, s in enumerate(matched_scenarios)])
            output = f"🔍 找到多个匹配的场景：\n{scenario_list}\n\n请选择具体的场景编号："
            return {
                **state,
                "output": output,
                "auto_continue": False,
                "messages": [AIMessage(content=output)]
            }
        else:
            # 没有匹配的场景
            available_scenarios = "\n".join([f"{i+1}. {s.get('场景名', 'N/A')}" for i, s in enumerate(test_scenarios)])
            output = f"❌ 未找到匹配的场景：'{user_input}'\n\n可用场景：\n{available_scenarios}\n\n请输入场景编号、场景名称、'全部'或'继续'"
            return {
                **state, 
                "output": output,
                "auto_continue": False,
                "messages": [AIMessage(content=output)]
            }
    
    return {
        **state,
        "selected_scenario": selected_scenario,
        "current_stage": "execute_test",
        "auto_continue": True,
        "output": output,
        "messages": [AIMessage(content=output)]
    }


async def execute_test(state: RequirementState) -> RequirementState:
    """节点：执行测试 - 真正复用 graph_builder.py 的执行逻辑"""
    logger.info("开始执行测试...")
    
    selected_scenario = state.get("selected_scenario")
    if not selected_scenario:
        output = "❌ 没有选中的测试场景"
        return {
            **state,
            "error_message": "没有选中的测试场景",
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }
    
    current_index = selected_scenario.get("current_index", 0)
    scenarios = selected_scenario.get("scenarios", [])
    total = selected_scenario.get("total", 0)
    
    # 🔧 修复1：在函数开始就检查是否所有场景都已执行完毕
    if current_index >= len(scenarios):
        # 所有场景执行完毕，构建最终摘要
        all_scenario_results = state.get("all_scenario_results", [])
        output = f"🎉 所有测试场景执行完毕！\n\n📊 **执行摘要**:\n"
        
        if all_scenario_results:
            for i, result in enumerate(all_scenario_results, 1):
                output += f"\n**场景{i}: {result['场景名']}**\n"
                for j, step_output in enumerate(result['执行结果'], 1):
                    # 截取输出的前100个字符避免过长
                    short_output = step_output[:100] + ('...' if len(step_output) > 100 else '')
                    output += f"  步骤{j}: {short_output}\n"
                output += f"  ✅ 场景执行完成\n"
            
            output += f"\n📈 **总结**: 共执行 {len(all_scenario_results)} 个场景，全部完成。"
        else:
            output += "⚠️ 未找到执行结果记录。"
        
        output += "\n\n✅ 工作流执行完毕"
        
        return {
            **state,
            "current_stage": "finish",
            "output": output,
            "auto_continue": False,
            "messages": [AIMessage(content=output)]
        }
    
    # 获取当前要执行的场景
    current_scenario = scenarios[current_index]
    scenario_name = current_scenario.get('场景名', 'N/A')
    interface_name = current_scenario.get('接口名', '')
    test_steps = current_scenario.get('测试步骤', [])
    
    if not test_steps:
        # 如果没有测试步骤，跳到下一个场景
        output = f"⚠️ 场景 '{scenario_name}' 没有测试步骤，跳过执行..."
        selected_scenario["current_index"] += 1
        return {
            **state,
            "selected_scenario": selected_scenario,
            "auto_continue": True,
            "output": output,
            "messages": [AIMessage(content=output)]
        }
    
    try:
        # 🔧 真正复用 graph_builder.py 中的执行逻辑
        # 获取MCP Agent执行器
        agent_executor = await get_mcp_agent()
        
        if agent_executor is None:
            output = f"⚠️ 场景 '{scenario_name}' 执行失败：无法连接到MCP服务，请确保所有MCP服务正在运行。"
            selected_scenario["current_index"] += 1
            return {
                **state,
                "selected_scenario": selected_scenario,
                "auto_continue": True,
                "output": output,
                "messages": [AIMessage(content=output)]
            }
        
        # 🔧 获取场景的默认请求报文（类似 graph_builder.py 中的 retrieve_steps）
        scene_data = await query_interface_details(interface_name, scenario_name)
        if not scene_data:
            logger.warning(f"未找到场景 '{scenario_name}' 的详细信息，使用默认数据")
            scene_data = {
                "接口中文名": interface_name,
                "场景名": scenario_name,
                "steps": test_steps if isinstance(test_steps, list) else [test_steps],
                "data": current_scenario
            }
        else:
            # 使用需求分析生成的测试步骤替换原始步骤
            scene_data["steps"] = test_steps if isinstance(test_steps, list) else [test_steps]
            scene_data["data"] = current_scenario
        
        # 执行每个测试步骤
        step_outputs = []
        step_results = []
        
        for step_idx, step in enumerate(scene_data["steps"]):
            logger.info(f"执行步骤 {step_idx + 1}: {step}")
            
            # 构建步骤特定的指令
            step_specific_instructions = ""
            if step_idx == 0:
                step_specific_instructions = STEP_1_PROMPT
            elif step_idx == 1:
                step_specific_instructions = STEP_2_PROMPT
            elif step_idx == 2:
                step_specific_instructions = STEP_3_PROMPT
            elif step_idx == 3:
                step_specific_instructions = STEP_4_PROMPT
            
            # 构建输入提示
            input_prompt = f"""
**当前场景**: `{scene_data.get("场景名")}`
**当前步骤描述**: `{step}`

---
**上下文数据**:
- **场景定义**: ```json
{json.dumps(scene_data, indent=2, ensure_ascii=False)}
```
- **已获取的测试数据**: ```json
{json.dumps(state.get("test_data"), indent=2, ensure_ascii=False)}
```
- **已构造的请求体**: ```json
{json.dumps(state.get("api_request_payload"), indent=2, ensure_ascii=False)}
```
- **上一步API响应**: ```json
{json.dumps(state.get("last_api_response"), indent=2, ensure_ascii=False)}
```
---
{step_specific_instructions}
"""
            
            try:
                # 调用Agent执行步骤
                response = await agent_executor.ainvoke({"input": input_prompt})
                
                # 处理响应
                final_output = response.get("output", "无输出")
                step_outputs.append(final_output)
                step_results.append(response)
                
                # 更新状态（类似 graph_builder.py 中的逻辑）
                new_state_updates = {}
                intermediate_steps = response.get("intermediate_steps", [])
                
                for action, result in intermediate_steps:
                    if hasattr(action, 'tool') and action.tool == "update_state":
                        tool_input = action.tool_input
                        if isinstance(tool_input, str):
                            try:
                                parsed_input = json.loads(tool_input)
                                if isinstance(parsed_input, dict) and "state_object" in parsed_input:
                                    new_state_updates.update(parsed_input["state_object"])
                            except json.JSONDecodeError:
                                continue
                        elif isinstance(tool_input, dict) and "state_object" in tool_input:
                            new_state_updates.update(tool_input["state_object"])
                

                
                # 应用状态更新
                state.update(new_state_updates)
                
                # 逻辑验证
                is_valid, validation_msg = await validate_step_logic(
                    step_description=step,
                    agent_final_output=final_output
                )
                
                if not is_valid:
                    logger.warning(f"步骤 {step_idx + 1} 逻辑验证失败: {validation_msg}")
                    step_outputs.append(f"⚠️ 逻辑验证失败: {validation_msg}")
                
            except Exception as e:
                logger.error(f"步骤 {step_idx + 1} 执行失败: {str(e)}")
                step_outputs.append(f"❌ 执行失败: {str(e)}")
        
        # 🔧 修复2：确保状态连续性 - 正确管理all_scenario_results
        if "all_scenario_results" not in state:
            state["all_scenario_results"] = []
        all_scenario_results = state["all_scenario_results"]
        
        # 保存当前场景的执行结果到状态中
        scenario_result = {
            "场景名": scenario_name,
            "执行结果": step_outputs
        }
        all_scenario_results.append(scenario_result)
        
        # 🔧 修复3：正确的索引管理 - 先更新索引再判断是否完成
        selected_scenario["current_index"] += 1
        new_current_index = selected_scenario["current_index"]
        
        # 判断是否所有场景都执行完毕
        if new_current_index >= total:
            # 所有场景执行完毕，构建最终摘要
            output = f"🎉 所有测试场景执行完毕！\n\n📊 **执行摘要**:\n"
            for i, result in enumerate(all_scenario_results, 1):
                output += f"\n**场景{i}: {result['场景名']}**\n"
                for j, step_output in enumerate(result['执行结果'], 1):
                    short_output = step_output[:100] + ('...' if len(step_output) > 100 else '')
                    output += f"  步骤{j}: {short_output}\n"
                output += f"  ✅ 场景执行完成\n"
            
            output += f"\n📈 **总结**: 共执行 {len(all_scenario_results)} 个场景，全部完成。"
            
            return {
                **state,
                "selected_scenario": selected_scenario,
                "all_scenario_results": all_scenario_results,
                "current_stage": "finish",
                "auto_continue": False,
                "output": output,
                "messages": [AIMessage(content=output)]
            }
        else:
            # 继续执行下一个场景，显示当前场景的执行结果
            current_scenario_output = f"✅ 场景 '{scenario_name}' 执行完成\n\n📋 **执行结果**:\n"
            for j, step_output in enumerate(step_outputs, 1):
                short_output = step_output[:100] + ('...' if len(step_output) > 100 else '')
                current_scenario_output += f"  步骤{j}: {short_output}\n"
            current_scenario_output += f"\n📄 继续执行下一个场景..."
            
            return {
                **state,
                "selected_scenario": selected_scenario,
                "all_scenario_results": all_scenario_results,
                "auto_continue": True,
                "output": current_scenario_output,
                "messages": [AIMessage(content=current_scenario_output)]
            }
        
    except Exception as e:
        logger.error(f"场景执行失败: {str(e)}")
        
        # 🔧 修复4：异常情况下也要正确保存结果
        if "all_scenario_results" not in state:
            state["all_scenario_results"] = []
        all_scenario_results = state["all_scenario_results"]
        
        # 保存失败场景的结果
        scenario_result = {
            "场景名": scenario_name,
            "执行结果": [f"❌ 执行失败: {str(e)}"]
        }
        all_scenario_results.append(scenario_result)
        
        selected_scenario["current_index"] += 1
        new_current_index = selected_scenario["current_index"]
        
        # 判断是否所有场景都执行完毕（包括失败的场景）
        if new_current_index >= total:
            output = f"🎉 所有测试场景执行完毕！\n\n📊 **执行摘要**:\n"
            for i, result in enumerate(all_scenario_results, 1):
                output += f"\n**场景{i}: {result['场景名']}**\n"
                for j, step_output in enumerate(result['执行结果'], 1):
                    short_output = step_output[:100] + ('...' if len(step_output) > 100 else '')
                    output += f"  步骤{j}: {short_output}\n"
                output += f"  ✅ 场景执行完成\n"
            
            output += f"\n📈 **总结**: 共执行 {len(all_scenario_results)} 个场景，全部完成。"
            
            return {
                **state,
                "selected_scenario": selected_scenario,
                "all_scenario_results": all_scenario_results,
                "current_stage": "finish",
                "auto_continue": False,
                "output": output,
                "messages": [AIMessage(content=output)]
            }
        else:
            # 继续执行下一个场景，显示当前场景的执行结果
            current_scenario_output = f"❌ 场景 '{scenario_name}' 执行失败\n\n📋 **失败原因**:\n{str(e)}\n\n📄 继续执行下一个场景..."
            
            return {
                **state,
                "selected_scenario": selected_scenario,
                "all_scenario_results": all_scenario_results,
                "auto_continue": True,
                "output": current_scenario_output,
                "messages": [AIMessage(content=current_scenario_output)]
            }

def handle_error(state: RequirementState) -> RequirementState:
    """节点：错误处理"""
    error_msg = state.get('error_message', '未知错误')
    logger.error(f"需求分析流程出错: {error_msg}")
    
    output = f"❌ 处理过程中发生错误: {error_msg}\n\n请检查输入并重试。"
    return {
        **state,
        "output": output,
        "auto_continue": False,
        "messages": [AIMessage(content=output)]
    }


# ======================
# 路由函数
# ======================
def requirement_router(state: RequirementState) -> str:
    """路由函数，决定下一个节点"""
    current_stage = state.get("current_stage")
    error_message = state.get("error_message")
    auto_continue = state.get("auto_continue", False)
    
    # 如果有错误，进入错误处理
    if error_message:
        return "handle_error"
    
    # 根据当前阶段路由
    if current_stage == "analyze_requirement":
        return "analyze_requirement"
    elif current_stage == "process_change":
        return "process_change"
    elif current_stage == "select_scenario":
        # 如果已经选择了场景，继续到执行测试
        if state.get("selected_scenario"):
            return "execute_test"
        # 如果没有用户输入，暂停等待
        if not state.get("user_input"):
            return END  # 暂停等待用户输入
        # 否则继续处理用户输入
        return "select_scenario"
    elif current_stage == "execute_test":
        return "execute_test"
    elif current_stage == "finish":
        return END
    
    # 默认开始分析
    return "analyze_requirement"


# ======================
# 工作流构建  
# ======================
async def build_requirement_workflow(checkpointer: BaseCheckpointSaver = None):
    """构建需求分析工作流"""
    logger.info("============构建需求分析工作流============")
    
    workflow = StateGraph(RequirementState)

    # 添加节点
    workflow.add_node("analyze_requirement", analyze_requirement)
    workflow.add_node("process_change", process_change)
    workflow.add_node("select_scenario", select_scenario)
    workflow.add_node("execute_test", execute_test)
    workflow.add_node("handle_error", handle_error)

    # 设置条件入口-路由
    workflow.set_conditional_entry_point(requirement_router)
    
    # 设置边关系 - 线性流程，不使用条件路由避免循环
    workflow.add_edge("analyze_requirement", "process_change")
    workflow.add_edge("process_change", "select_scenario") 
    
    # select_scenario 需要条件路由：如果已选择场景则继续执行，否则等待用户输入
    workflow.add_conditional_edges(
        "select_scenario",
        requirement_router,
        {
            "select_scenario": "select_scenario",  # 继续处理用户输入
            "execute_test": "execute_test",        # 已选择场景，开始执行
            END: END                               # 暂停等待用户输入
        }
    )
    
    # execute_test 可以循环执行多个场景，或结束
    workflow.add_conditional_edges(
        "execute_test",
        lambda state: "execute_test" if state.get("auto_continue") else "finish",
        {
            "execute_test": "execute_test",
            "finish": END
        }
    )
    
    workflow.add_edge("handle_error", END)

    # 编译工作流
    if checkpointer:
        compiled_workflow = workflow.compile(checkpointer=checkpointer)
        logger.info("需求分析工作流创建成功，已配置checkpointer")
    else:
        compiled_workflow = workflow.compile()
        logger.info("需求分析工作流创建成功")
    
    return compiled_workflow





# ======================
# 主执行流程（CLI模式测试）
# ======================
async def main():
    """主执行流程 - 使用图工作流测试"""
    print("=== 需求分析工作流测试 ===")
    
    # 文件选择
    files = ["1.纯逻辑变更.md", "2.字典值变更.md", "3.新增必输字段.md", "4.新增选输字段.md"]
    print("\n可选的需求文档:")
    for i, f in enumerate(files, 1):
        print(f"{i}. {f}")
    
    try:
        choice = input("\n请输入选择的需求文档编号 (1-4): ").strip()
        if not choice.isdigit() or int(choice) < 1 or int(choice) > 4:
            print("❌ 无效的选择")
            return
            
        file_name = files[int(choice) - 1]
        file_path = f"docs/requirements/{file_name}"
        
        # 读取文档内容
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            document_content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
        
        print(f"\n📄 正在分析文档: {file_name}")
        print("=" * 50)
        
        # 构建并执行工作流
        db_manager = DatabaseManager()
        await db_manager.initialize()
        checkpointer = db_manager.get_checkpointer()
        
        workflow = await build_requirement_workflow(checkpointer)
        initial_state = create_initial_requirement_state(document_content)
        
        config = {"configurable": {"thread_id": f"test_{file_name}_{int(asyncio.get_event_loop().time())}"}}
        
        try:
            # 🔧 交互式执行工作流
            current_state = initial_state
            
            while True:
                # 执行工作流到下一个暂停点
                result = await workflow.ainvoke(current_state, config)
                
                # 获取当前状态
                state = await workflow.aget_state(config)
                current_values = state.values
                
                # 打印当前输出
                if current_values.get("output"):
                    print(f"\n🤖 {current_values['output']}")
                
                # 检查是否需要用户输入
                if (current_values.get("current_stage") == "select_scenario" and 
                    not current_values.get("selected_scenario")):
                    # 等待用户输入场景选择
                    user_input = input("\n请输入选择: ").strip()
                    current_state = {
                        "user_input": user_input,
                        "messages": [HumanMessage(content=user_input)]
                    }
                else:
                    # 检查工作流是否已完成
                    if not state.next:
                        print(f"\n✅ 工作流执行完毕")
                        break
                    
                    # ⚠️ 修复：继续执行时保留完整的状态
                    current_state = current_values
        finally:
            # 确保数据库连接正确关闭
            await db_manager.close()
            
    except FileNotFoundError:
        print(f"❌ 文件未找到: {file_path}")
    except Exception as e:
        print(f"❌ 执行失败: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")
