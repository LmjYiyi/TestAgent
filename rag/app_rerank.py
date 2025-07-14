from langchain.retrievers import ContextualCompressionRetriever
from langchain_community.document_loaders import PyMuPDFLoader
# from langchain_community.llms.dquestion import DQuestion
# from langchain_community.chat_models.openai import ChatOpenAI
from langchain_openai import ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.chains.retrieval_qa.base import RetrievalQA
from models import dquestion
from dotenv import load_dotenv
import os

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_API_BASE")

# 加载pdf
docs = PyMuPDFLoader("杭州.pdf").load()
text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
# 对文本进行拆分
documents = text_splitter.split_documents(docs)
# 嵌入模型
embeddings = dquestion.get_embedding()
# 将数据存入faiss的向量存储器
vector = FAISS.from_documents(documents, embeddings)
# 加载文档--》拆分文档--》嵌入--》检索器
retriever = vector.as_retriever(
    search_kwargs={
        "k": 10,
    }
)

# 获取重排模型
compressor = dquestion.get_reranker()
compression_retriever = ContextualCompressionRetriever(
    base_compressor=compressor, base_retriever=retriever
)
query = "介绍一下杭州的环境"
compressed_docs = compression_retriever.get_relevant_documents(query)
dquestion.pretty_print_docs(compressed_docs)
llm = ChatOpenAI(
    model="deepseek-ai/DeepSeek-R1", 
    openai_api_key=api_key,
    openai_api_base=base_url)
# 基于问答格式输出(DQuestion 可以替换成 OpenAI大模型)
chain = RetrievalQA.from_chain_type(
    llm=llm, retriever=compression_retriever
)

response = chain.invoke({"query": query})
print(response)
