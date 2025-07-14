from .siliconFlowEmbeddings import SiliconFlowEmbeddings
from .siliconFlowRerank import SiliconFlowRerank
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os

# 请在.env文件中设置相应环境变量
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_API_BASE")

def get_llm():
    llm = ChatOpenAI(
    # model="deepseek-ai/DeepSeek-R1", 
    model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
    openai_api_key= api_key,
    openai_api_base= base_url,
    temperature = 0.5,
    streaming=True)
    return llm

def get_embedding():
    # 这里可以替换成开源嵌入模型
    # embeddings = OpenAIEmbeddings()
    embeddings = SiliconFlowEmbeddings(
        api_key=api_key,
        api_base_url=base_url,
        model_name="BAAI/bge-large-zh-v1.5",
        batch_size=16,  # SiliconFlow 文档提到每个请求的 token 限制为 2048，
        # 并且输入数组长度最大为 256。批处理文本更安全。
        # 16-32 个文本的 batch_size 应该是合理的。
    )
    return embeddings

def get_reranker():
    # 这里可以替换成开源重排模型
    compressor = SiliconFlowRerank(
        api_key=api_key,
        base_url=f"{base_url}/rerank",
        model="BAAI/bge-reranker-v2-m3",
        top_n=5,
        return_documents=True,
    )
    return compressor


def pretty_print_docs(docs):
    print(
        f"\n{'-' * 100}\n".join(
            [f"Document {i + 1}:\n\n" + d.page_content for i, d in enumerate(docs)]
        )
    )
