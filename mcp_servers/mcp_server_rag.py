import sys
sys.path.append('D:/TCGT')
# for pth in sys.path:
#     print(pth)

import os
import re
from typing import List
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain.retrievers import ContextualCompressionRetriever
from langchain.chains import RetrievalQA
from models import dquestion
from fastmcp import FastMCP

import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')  # 强制 UTF-8
# 创建 FastMCP 实例
mcp = FastMCP('RAG')


# 环境变量加载
def load_environment():
    load_dotenv("../.env")
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
def create_retriever(vectorstore, reranker):
    return ContextualCompressionRetriever(
        base_retriever=vectorstore.as_retriever(search_kwargs={
            "filter": {'类型': '接口场景'},  # 根据实际情况构建过滤条件
            'k': 20
        }),
        base_compressor=reranker,  # 重排模型
    )


# 创建问答链
def create_qa_chain(retriever):
    return RetrievalQA.from_chain_type(
        llm=dquestion.get_llm(),
        retriever=retriever,
        return_source_documents=True,
    )


def create_prompt(query: str) -> str:
    prompt = f"""
    请严格按照以下规则处理用户查询：

    ## 任务目标
    从检索到的文档中，提取 **metadata 中的「接口中文名」和「场景名」**，生成结构化列表。

    ## 关键约束
    1. **字段来源唯一**：必须从文档的 `metadata` 字典中提取，**绝对禁止** 使用文档内容（page_content）中的任何文字。
    2. **字段名固定**：仅提取 `metadata` 中的 `接口中文名` 和 `场景名` 两个字段，忽略其他字段。
    3. **原始值保留**：直接使用字段的原始值，不增删、不改写任何字符（包括标点符号）。
    4. **输出格式强制**：
       - 仅返回一行代码：`api_list = ["接口中文名: <值>, 场景名: <值>", ...]`
       - 列表项用英文双引号包裹，逗号分隔，无额外空行或解释。

    ## 正确示例
    输入文档的 metadata：
    {{
        "接口中文名": "订单查询",
        "场景名": "普通订单查询", 
        "其他字段": "...",
        "page_content": "用户通过提供订单ID和用户ID进行订单查询..."  # 文档内容（忽略！）
    }}

    正确输出：
    api_list = ["接口中文名: 订单查询, 场景名: 普通订单查询"]

    ## 错误示例（必须避免）
    ❌ 错误1（使用文档内容作为场景名）：
    api_list = ["接口中文名: 订单查询, 场景名: 用户通过提供订单ID和用户ID进行订单查询"]  # 错误！场景名必须是 metadata 中的「普通订单查询」

    ❌ 错误2（修改字段值）：
    api_list = ["接口中文名: 订单查询接口, 场景名: 普通查询"]  # 错误！必须保留原始值「订单查询」「普通订单查询」

    ## 你的任务
    用户查询：{query}
    请返回符合上述所有要求的结果，不得添加任何额外内容。
    """
    return prompt.strip()  # 去除首尾空行，避免格式干扰


# 主函数，执行查询
@mcp.tool()
def rag_match(query: str):
    """
        使用 RAG 检索模型进行场景检索。
        :param query: 用户查询内容
        :return: 检索到的相关场景列表
    """
    # 加载环境变量
    load_environment()

    # 加载文档
    md_dir = "../docs/knowledge"
    documents = load_documents(md_dir)
    # print(documents)

    # 初始化嵌入模型
    embedding_model = initialize_embedding_model()

    # 设置向量数据库路径
    persist_path = "../db/siliconflow_vector_db"
    vectorstore = load_or_create_vectorstore(documents, embedding_model, persist_path)

    # 初始化重排器
    reranker = dquestion.get_reranker()

    # 创建检索器
    retriever = create_retriever(vectorstore, reranker)

    # 创建问答链
    qa_chain = create_qa_chain(retriever)

    prompt = create_prompt(query)

    # 提问并输出结果
    answer = qa_chain.invoke({"query": prompt})

    print(f"\n❓ 问题：{query}")

    return answer


if __name__ == '__main__':
    mcp.run(transport="stdio")
# if __name__ == "__main__":
#     user_query = "我想要订单查询相关的所有场景列表"
#     answer = rag_match(user_query)
#     print(answer['result'])
