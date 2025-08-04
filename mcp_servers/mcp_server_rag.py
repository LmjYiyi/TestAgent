import json
import sys
import os

from langchain_core.messages import AIMessage

current_path = os.path.dirname(os.path.abspath(__file__)) # 当前文件所在目录
main_dir = os.path.dirname(current_path) # 项目根目录
sys.path.append(main_dir)
from utils.logger import logger
import re
from typing import List, Optional, Tuple, Dict
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma
from langchain.retrievers import ContextualCompressionRetriever
from langchain.chains.retrieval_qa.base import RetrievalQA
from models import dquestion
from fastmcp import FastMCP
from langchain.prompts import PromptTemplate
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')  # 强制 UTF-8
# 创建 FastMCP 实例
mcp = FastMCP('RAG')

# # 环境变量加载
# def load_environment():
#     load_dotenv("/.env")
#     api_key = os.getenv("SILICONFLOW_API_KEY")
#     base_url = os.getenv("SILICONFLOW_API_BASE")
#     return api_key, base_url

# 加载 Markdown 文档
def load_documents(md_dir: str) -> List[Document]:
    md_paths = [os.path.join(md_dir, f) for f in os.listdir(md_dir) if f.endswith('.md')]
    documents = []

    for md_path in md_paths:
        with open(md_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        # 提取公共字段 metadata
        header_match = re.search(r"^# 接口基本信息.*?$", raw_text, flags=re.MULTILINE)
        header_start = header_match.start() if header_match else 0
        next_block_match = re.search(r"^# (?!接口基本信息).*?$", raw_text[header_start:], flags=re.MULTILINE)
        header_end = header_start + next_block_match.start() if next_block_match else len(raw_text)
        base_block = raw_text[header_start:header_end]

        def extract_star_fields(text: str):
            return dict(re.findall(r"\*\*(.+?)\*\*\s*:\s*(.+)", text))

        base_metadata = extract_star_fields(base_block)

        content_blocks = re.split(r"(?=^# (?!接口基本信息).*)", raw_text[header_end:], flags=re.MULTILINE)

        for block in content_blocks:
            if not block.strip():
                continue
            block_meta = extract_star_fields(block)
            full_meta = base_metadata.copy()
            full_meta.update(block_meta)
            content = re.sub(r"\*\*.+?\*\*\s*:.+\n?", "", block).strip()
            documents.append(Document(page_content=content, metadata=full_meta))

    return documents


# 初始化嵌入模型
def initialize_embedding_model():
    return dquestion.get_embedding()


# 加载或创建向量数据库
def load_or_create_vectorstore(documents: List[Document], embedding_model, persist_path: str):
    db_empty = (
            not Path(persist_path).exists() or  # 目录不存在
            not any(Path(persist_path).glob("*.sqlite3")) and  # 缺少 sqlite3 文件
            not any(Path(persist_path).glob("*.bin"))  # 缺少 bin 文件
    )

    if db_empty:
        print("🔄 向量库不存在或为空，开始嵌入文档...")
        vectorstore = Chroma.from_documents(
            documents=documents,
            embedding=embedding_model,
            persist_directory=persist_path
        )
        print("✅ 嵌入完成并持久化。")
    else:
        print("✅ 向量库已存在，直接加载。")
        vectorstore = Chroma(
            persist_directory=persist_path,
            embedding_function=embedding_model
        )

    return vectorstore


# 创建检索器
def create_retriever(vectorstore: Chroma, reranker):
    return ContextualCompressionRetriever(
        base_retriever=vectorstore.as_retriever(
            search_type="similarity_score_threshold",
            search_kwargs={
                "score_threshold": 0.2,
                "filter": {'类型': '接口场景'},  # 根据实际情况构建过滤条件
                'k': 20
            }
        ),
        base_compressor=reranker,  # 重排模型
    )


# 直接生成 api_list
def generate_api_list(documents: List[Document], query: str) -> str:
    api_list = []

    # 根据用户查询从检索的文档中提取接口信息
    for doc in documents:
        metadata = doc.metadata
        interface_name = metadata.get("接口中文名")
        scene_name = metadata.get("场景名")

        if interface_name and scene_name:
            api_list.append(f'接口中文名: {interface_name}, 场景名: {scene_name}')

    # 格式化输出 api_list
    return f'api_list = [{", ".join(api_list)}]'


# 抽取指定场景的步骤
def extract_steps(page_content: str) -> List[str]:
    """
    从文档内容中提取操作步骤列表
    参数:
        page_content: 包含步骤的文本内容
    返回:
        格式化后的步骤列表（去除编号和多余空格）
    """
    if not page_content:
        return []

    try:
        # 提取步骤部分（从"步骤："开始到下一个标题或结束）
        steps_part = re.split(r'步骤：\s*', page_content, flags=re.IGNORECASE)[-1]
        steps_part = re.split(r'\n\s*#{1,3}\s+|\n---', steps_part)[0]

        # 匹配所有带编号的步骤行
        steps = re.findall(r'\d+\.\s*(.+?)\s*$', steps_part, flags=re.MULTILINE)
        return [step.strip() for step in steps if step.strip()]

    except Exception as e:
        print(f"步骤提取出错: {e}")
        return []

# 接口场景检索工具
@mcp.tool()
def rag_match(query: str):
    """
        使用 RAG 检索模型进行场景检索。
        :param query: 用户查询内容
        :return: 检索到的相关场景列表
    """
    print("RAG_MATCH工具正在处理，输入query：{query}")
    # 加载环境变量
    # load_environment()

    # 加载文档
    md_dir = "docs/knowledge"
    documents = load_documents(md_dir)

    # 初始化嵌入模型
    embedding_model = initialize_embedding_model()

    # 设置向量数据库路径
    persist_path = "db/siliconflow_vector_db"
    vectorstore = load_or_create_vectorstore(documents, embedding_model, persist_path)

    # 初始化重排器
    reranker = dquestion.get_reranker()

    # 创建检索器
    retriever = create_retriever(vectorstore, reranker)

    # 使用 invoke() 获取与查询相关的文档
    relevant_docs = retriever.invoke(query)

    # 生成 API 列表
    api_list = generate_api_list(relevant_docs, query)

    print(f"\n❓ 问题：{query}")

    return api_list


# 指定场景步骤检索工具
@mcp.tool()
def get_api_steps(interface_name: str, scenario_name: str) -> Optional[List[str]]:
    """
    获取指定接口中文名和场景名的操作步骤
    参数:
        interface_name: 接口中文名 (如"用户注册")
        scenario_name: 场景名 (如"普通用户注册")
    返回:
        操作步骤列表 (成功时)
        None (失败时)
    """
    try:
        # 1. 初始化向量数据库
        persist_path = "db/siliconflow_vector_db"
        vectorstore = Chroma(
            persist_directory=persist_path,
            embedding_function=dquestion.get_embedding()
        )

        # 2. 创建带过滤条件的检索器
        retriever = vectorstore.as_retriever(
            search_kwargs={
                "filter": {
                    "$and": [
                        {"接口中文名": {"$eq": interface_name}},
                        {"场景名": {"$eq": scenario_name}}
                    ]
                },
                "k": 1  # 只返回最相关的1个文档
            }
        )

        # 3. 执行检索
        docs = retriever.invoke(f"步骤")

        if not docs:
            print(f"未找到匹配文档 - 场景名: {scenario_name}, 接口名: {interface_name}")
            return None

        # 4. 提取并返回步骤
        steps = extract_steps(docs[0].page_content)
        return steps if steps else None

    except Exception as e:
        print(f"操作步骤获取失败: {e}")
        return None


def retrieve_interface_data(interface_name: str) -> Optional[Tuple[Dict, str, str]]:
    """从向量数据库检索接口元数据和原始表格内容"""
    try:
        persist_path = "db/siliconflow_vector_db"  # 替换为你的向量库路径
        vectorstore = Chroma(
            persist_directory=persist_path,
            embedding_function=dquestion.get_embedding()
        )

        # 检索"接口中文名+类型=通用请求参数"的文档
        params_retriever = vectorstore.as_retriever(
            search_kwargs={
                "filter": {
                    "$and": [
                        {"接口中文名": {"$eq": interface_name}},
                        {"类型": {"$eq": "通用请求参数"}}
                    ]
                },
                "k": 1
            }
        )
        header_retriever = vectorstore.as_retriever(
            search_kwargs={
                "filter": {
                    "$and": [
                        {"接口中文名": {"$eq": interface_name}},
                        {"类型": {"$eq": "通用请求头"}}
                    ]
                },
                "k": 1
            }
        )
        params_docs = params_retriever.invoke(f"接口中文名：{interface_name}，类型：通用请求参数")
        header_docs = header_retriever.invoke(f"接口中文名：{interface_name}，类型：通用请求头")
        if not params_docs:
            print(f"未找到接口'{interface_name}'的【通用请求参数】文档")
            return None
        if not header_docs:
            print(f"未找到接口'{interface_name}'的【通用请求头】文档")
            return None

        # 返回元数据和page_content（原始表格）
        params_doc = params_docs[0]
        header_doc = header_docs[0]
        return params_doc.metadata, params_doc.page_content, header_doc.page_content

    except Exception as e:
        print(f"接口数据检索失败: {str(e)}")
        return None


def generate_request_prompt(metadata: Dict, params_content: str, headers_content: str) -> str:
    """生成结构化提示词，明确目标报文格式"""
    # 格式化元数据为可读性文本
    metadata_str = "\n".join([f"- {k}: {v}" for k, v in metadata.items()])

    # 提示词模板（核心：明确完整报文结构要求）
    return f"""
    任务：基于接口元数据，请求头表格，参数表格，生成完整的请求报文JSON，格式需严格匹配示例结构。

    === 接口元数据（提取URL和method）===
    {metadata_str}
    说明：请从元数据中提取"URL"作为报文的"url"字段，提取"请求方式"作为"method"字段。

     === 请求头内容（生成headers字段）===
    {headers_content}
    说明：请从表格中提取请求头信息，按以下规则构造"headers"字段：
    1. 表格中的"请求头字段名"作为key，"示例值"作为value（若"示例值"为"-"则留空字符串）。
    2. 必填项："是否必输"为"是"的参数必须包含。

    === 参数表格（提取json_body内容）===
    {params_content}
    说明：请从表格中提取参数，按以下规则构造"json_body"字段：
    1. 父子参数规则："object"类型参数（如counterParams）是嵌套对象，其下方"├─"/"└─"前缀的参数（如counter_account）作为子字段。
    2. 必填项："是否必输"为"是"的参数必须包含，全部使用默认示例值填充，示例值为"-"则留空字符串。
    3. 非必填项："是否必输"为"否"的参数也必须包含，全部使用默认示例值填充，示例值为"-"则留空字符串。

    === 目标报文格式（严格遵循！）===
    {{
        "url": "[从元数据提取的URL]",
        "method": "[从元数据提取的请求方式]",
        "headers": {{
            // 从表格提取的请求头信息，示例：
            "Content-Type": "application/json",
            "X-Request-App": "ICBC_TestAgent",
            "X-Request-Id": "req_base_001" 
        }},
        "json_body": {{
            // 从表格提取的参数，按层级嵌套，示例：
            "顶级参数": "示例值",
            "object参数": {{
                "子参数": "子参数示例值"
            }}
        }}
    }}

    输出要求：
    1. 仅返回纯JSON，无任何解释文字，确保可直接解析。
    2. "url"和"method"必须从元数据提取，不可使用示例值。
    3. "headers"严格按表格内容构造。
    4. "json_body"严格按表格参数构造，确保父子嵌套正确，同时返回所有参数内容，不可遗漏。
    """


def call_llm_generate(prompt: str) -> Optional[Dict]:
    """调用预定义模型生成完整报文"""
    try:
        # 获取预定义模型
        llm = dquestion.get_llm()

        # 调用模型生成响应（返回AIMessage对象）
        response = llm.invoke(prompt)

        # 1. 提取content（处理AIMessage）
        if isinstance(response, AIMessage):
            response_content = response.content
        else:
            response_content = str(response)

        # 2. 增强清理：移除所有非JSON必要字符
        # 步骤1：移除```json和```标记（支持多行标记）
        cleaned = re.sub(r'^```json\s*', '', response_content, flags=re.IGNORECASE | re.MULTILINE)
        cleaned = re.sub(r'\s*```$', '', cleaned, flags=re.MULTILINE)
        # 步骤2：移除开头/结尾的所有空白字符（包括换行、制表符、零宽字符）
        cleaned = re.sub(r'^\s+', '', cleaned, flags=re.MULTILINE)  # 移除开头空白
        cleaned = re.sub(r'\s+$', '', cleaned, flags=re.MULTILINE)  # 移除结尾空白
        # 步骤3：移除可能的BOM头（Windows生成的文件可能有）
        cleaned = cleaned.lstrip('\ufeff')

        # 3. 验证清理结果（打印日志，方便调试）
        # print(f"\n--- 清理后的JSON内容 ---")
        # print(cleaned[:500])  # 打印前500字符，确认无异常字符

        # 4. 解析JSON
        return json.loads(cleaned)

    except json.JSONDecodeError as e:
        print(f"\nJSON解析失败: {str(e)}")
        print(f"问题位置: 行{e.lineno}，列{e.colno}")
        print(f"错误内容预览: {cleaned[e.pos - 20:e.pos + 20]}")  # 打印错误位置前后字符
        return None
    except Exception as e:
        print(f"模型调用失败: {str(e)}")
        return None


@mcp.tool()
def generate_api_request(interface_name: str) -> Optional[Dict]:
    """
    生成指定接口的完整请求报文（封装主流程）

    参数:
        interface_name: 接口中文名（如"商品库存查询"）

    返回:
        完整请求报文字典（包含url/method/headers/json_body），失败返回None
    """
    # print(f"=== 开始生成'{interface_name}'接口完整请求报文 ===")

    # 1. 检索元数据、参数表格、请求头表格
    request_data = retrieve_interface_data(interface_name)
    if not request_data:
        print(f"❌ 接口'{interface_name}'数据检索失败，流程终止")
        return None
    metadata, param_content, header_content = request_data

    # 2. 生成提示词
    prompt = generate_request_prompt(metadata, param_content, header_content)
    # print("\n--- 提示词预览 ---")
    # print(prompt)  # 打印前800字符，避免日志过长

    # 3. 调用模型生成完整报文
    full_request = call_llm_generate(prompt)
    if not full_request:
        print(f"❌ 接口'{interface_name}'报文生成失败")
        return None

    # 4. 返回结果（字典格式）
    return full_request


def retrieve_response_data(interface_name: str) -> str:
    """从向量数据库检索接口元数据和原始表格内容"""
    try:
        persist_path = "db/siliconflow_vector_db"  # 替换为你的向量库路径
        vectorstore = Chroma(
            persist_directory=persist_path,
            embedding_function=dquestion.get_embedding()
        )

        # 检索"接口中文名+类型=通用响应参数"的文档
        params_retriever = vectorstore.as_retriever(
            search_kwargs={
                "filter": {
                    "$and": [
                        {"接口中文名": {"$eq": interface_name}},
                        {"类型": {"$eq": "通用响应参数"}}
                    ]
                },
                "k": 1
            }
        )
        params_docs = params_retriever.invoke(f"接口中文名：{interface_name}，类型：通用响应参数")
        if not params_docs:
            print(f"未找到接口'{interface_name}'的【通用响应参数】文档")
            return None
        # 返回page_content（原始表格）
        params_doc = params_docs[0]
        return params_doc.page_content

    except Exception as e:
        print(f"接口数据检索失败: {str(e)}")
        return None


def generate_response_prompt(params_content: str) -> str:
    """生成结构化提示词，明确目标报文格式"""
    # 提示词模板（核心：明确完整报文结构要求）
    return f"""
    任务：基于响应参数表格，生成完整的响应报文JSON，格式需严格匹配示例结构。

    === 参数表格（提取各响应参数内容）===
    {params_content}
    说明：请从表格中提取参数，按以下规则构造响应报文：
    1. 父子参数规则："object"类型参数是嵌套对象，其下方"├─"/"└─"前缀的参数作为子字段。
    2. 必填项："是否必输"为"是"的参数必须包含，全部使用默认示例值填充，示例值为"-"则留空字符串。
    3. 非必填项："是否必输"为"否"的参数也必须包含，全部使用默认示例值填充，示例值为"-"则留空字符串。

    === 目标报文格式（严格遵循！）===
    {{
       // 从表格提取的参数，可能包含多层级嵌套，注意识别，示例：
        "顶级参数1": "示例值",
        "顶级参数2": "示例值",
        "父级object参数": {{
            "子参数": "子参数示例值"
            "子级object参数": {{
                "子参数1": "子参数示例值"
                "子参数2": "子参数示例值"
            }}
        }}
    }}

    输出要求：
    1. 仅返回纯JSON，无任何解释文字，确保可直接解析。
    2. "严格按表格参数构造，确保父子嵌套正确，同时返回所有参数内容，不可遗漏某些参数以及某些子级参数。
    """


@mcp.tool()
def generate_api_response(interface_name: str) -> Optional[Dict]:
    """
    生成指定接口的完整响应报文（封装主流程）

    参数:
        interface_name: 接口中文名（如"商品库存查询"）

    返回:
        完整响应报文字典（包含响应参数的值），失败返回None
    """
    # print(f"=== 开始生成'{interface_name}'接口完整响应报文 ===")

    # 1. 检索响应参数表格
    response_data = retrieve_response_data(interface_name)
    if not response_data:
        print(f"❌ 接口'{interface_name}'数据检索失败，流程终止")
        return None
    param_content = response_data

    # 2. 生成提示词
    prompt = generate_response_prompt(param_content)
    # print("\n--- 提示词预览 ---")
    # print(prompt)  # 打印前800字符，避免日志过长

    # 3. 调用模型生成完整报文
    full_request = call_llm_generate(prompt)
    if not full_request:
        print(f"❌ 接口'{interface_name}'报文生成失败")
        return None

    # 4. 返回结果（字典格式）
    return full_request


def main():
    """启动RAG-MCP服务器"""
    logger.info("启动RAG调用MCP服务器...")
    try:
        mcp.run(transport='stdio')
    except KeyboardInterrupt:
        logger.info("\n服务器被用户中断，正在关闭...")


if __name__ == '__main__':
    main()