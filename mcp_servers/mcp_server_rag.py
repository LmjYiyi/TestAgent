import sys
import os
current_path = os.path.dirname(os.path.abspath(__file__)) # 当前文件所在目录
main_dir = os.path.dirname(current_path) # 项目根目录
sys.path.append(main_dir)
from utils.logger import logger
import re
from typing import List, Optional
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

# 环境变量加载
def load_environment():
    load_dotenv("/.env")
    api_key = os.getenv("SILICONFLOW_API_KEY")
    base_url = os.getenv("SILICONFLOW_API_BASE")
    return api_key, base_url

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
            content = block.strip()
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
                "score_threshold": 0.4,
                "filter": {'类型': '接口场景'},  # 根据实际情况构建过滤条件
                'k': 5
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
    load_environment()

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
        docs = retriever.invoke(f"{scenario_name}流程") or retriever.invoke(f"{interface_name}步骤")

        if not docs:
            print(f"未找到匹配文档 - 场景名: {scenario_name}, 接口名: {interface_name}")
            return None

        # 4. 提取并返回步骤
        steps = extract_steps(docs[0].page_content)
        return steps if steps else None

    except Exception as e:
        print(f"操作步骤获取失败: {e}")
        return None


def main():
    """启动RAG-MCP服务器"""
    logger.info("启动RAG调用MCP服务器...")
    try:
        mcp.run(transport='stdio')
    except KeyboardInterrupt:
        logger.info("\n服务器被用户中断，正在关闭...")

if __name__ == '__main__':
    main()