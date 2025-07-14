"""
根据输入，返回接口中文名列表
"""

from langchain_community.document_loaders import TextLoader
from langchain_openai import ChatOpenAI
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import MarkdownHeaderTextSplitter
from langchain.chains.retrieval_qa.base import RetrievalQA
from dotenv import load_dotenv
import os

from models import dquestion

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_API_BASE")

def mdretriever(persist_directory, collection, filter, query):
    embeddings = dquestion.get_embedding()
    vectorstore = Chroma(persist_directory=persist_directory, embedding_function=embeddings, collection_name=collection)
    retriever = vectorstore.as_retriever(
        search_kwargs={
            "k": 10,
            "filter": filter,
        }
    )

    docs = retriever.invoke(query)

    dquestion.pretty_print_docs(docs)

    llm = ChatOpenAI(
        model="deepseek-ai/DeepSeek-R1",
        temperature=0,
        openai_api_key=api_key,
        openai_api_base=base_url)

    chain = RetrievalQA.from_chain_type(
        llm=llm, retriever=retriever
    )

    response = chain.invoke({"query": query})
#    print(f"方法中的输出：{response}")

    return response


if __name__ == '__main__':
    persist_directory = "../md_db"
    collection = "md_collection"
    filter = {"Header 2": {"$eq": "接口信息"}}
    query = "给我一个接口中文名列表"
    mdretriever(persist_directory, collection, filter, query)