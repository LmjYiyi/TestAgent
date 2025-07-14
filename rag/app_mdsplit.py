""""
对MD文档进行拆分，转成vector格式，存入本地向量数据库
对文档格式有一定要求，见test/统一认证用户信息查询接口文档.md

"""

from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import MarkdownHeaderTextSplitter
from langchain.chains.retrieval_qa.base import RetrievalQA
from models import dquestion
from dotenv import load_dotenv
import os

# 请在.env文件中设置相应环境变量
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_API_BASE")

def mdsplit(markdown_path,persist_directory,collection):
    # 加载pdf，加载时元数据已设置好
    loader = TextLoader(markdown_path,encoding="utf-8",autodetect_encoding=True)
    docs = loader.load()

    headers_to_split_on = [
        ("###", "Header 1"),
        ("####", "Header 2"),
        ("#####", "Header 3"),
    ]
    text_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    # 对文本进行拆分
    documents = text_splitter.split_text(docs[0].page_content)
    # 嵌入模型
    embeddings = dquestion.get_embedding()
    # 将数据存入chroma的向量存储器
    vector = Chroma.from_documents(documents, embeddings, persist_directory=persist_directory, collection_name=collection)
    print()

if __name__ == '__main__':
    markdown_path = "../test/统一认证用户信息查询接口文档.md"
    persist_directory = "../md_db"
    collection = "md_collection"
    mdsplit(markdown_path, persist_directory, collection)


