from fastmcp import FastMCP
from typing import List, Dict
import re
import chromadb
from sentence_transformers import SentenceTransformer, CrossEncoder

# 创建 FastMCP 实例
mcp = FastMCP()


# # 定义工具函数
# @mcp.tool()
# def get_weather(city: str):
#     """
#     获取对应城市的天气
#     :param city: 城市
#     :return: 城市天气的描述
#     """
#     return f"{city}今天天气晴，18度"


# 1. 场景检索器类
class EnhancedScenarioRetriever:
    def __init__(self, model_path: str = "../model_cache"):
        # 初始化模型
        self.embedding_model = SentenceTransformer(model_path)
        self.rerank_model = CrossEncoder("../cross_encoder")

        # 初始化向量数据库
        self.client = chromadb.EphemeralClient()
        self.collection = self.client.get_or_create_collection("scenarios")

        # 存储场景数据
        self.scene_data: Dict[str, dict] = {}

    def load_scenarios(self, filepath: str):
        """加载场景知识库文档"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # 分割场景
        scenarios = [s.strip() for s in re.split(r'^# .+$', content, flags=re.MULTILINE) if s.strip()]

        chunks = []
        embeddings = []

        for i, scenario in enumerate(scenarios):
            if not scenario:
                continue

            # 解析场景名称(第一行)
            scene_name = scenario.split('\n')[0].strip()

            # 存储完整场景信息
            self.scene_data[scene_name] = self._parse_scenario(scenario)

            # 生成嵌入
            embedding = self.embedding_model.encode(scenario, normalize_embeddings=True)

            chunks.append(scenario)
            embeddings.append(embedding.tolist())

        # 存入向量数据库
        self.collection.add(
            documents=chunks,
            embeddings=embeddings,
            ids=[str(i) for i in range(len(chunks))]
        )

    def _parse_scenario(self, scenario: str) -> dict:
        """解析单个场景的详细信息,读取知识库时调用"""
        lines = scenario.split('\n')
        info = {
            "name": lines[0].strip(),
            "description": "",
            "interface": {},
            "steps": []
        }

        # 提取基本信息
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue

            if line.startswith("**功能**"):
                info["description"] = line.split("：")[1].strip()
            elif line.startswith("**接口**"):
                interface_str = line.split("`")[1]
                method, endpoint = interface_str.split()
                info["interface"] = {
                    "method": method,
                    "endpoint": endpoint,
                    "parameters": {}
                }
            elif line.startswith("- ") and ":" in line and "interface" in info:
                param_line = line[2:].split(":", 1)
                param_name = param_line[0].split("(")[0].strip()
                info["interface"]["parameters"][param_name] = param_line[1].strip()
            elif line[0].isdigit():
                info["steps"].append(line.split(".", 1)[1].strip())

        return info

    def retrieve_scenes(self, query: str, top_k: int = 10) -> List[dict]:
        """检索并排序场景"""
        # 第一步：向量检索
        query_embedding = self.embedding_model.encode(query, normalize_embeddings=True).tolist()
        vector_results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k * 2  # 扩大检索范围用于重排序
        )

        # 第二步：重排序
        pairs = [(query, doc) for doc in vector_results['documents'][0]]
        scores = self.rerank_model.predict(pairs)

        # 组合结果并排序
        scored_results = []
        for i, (doc, score) in enumerate(zip(vector_results['documents'][0], scores)):
            scene_name = doc.split('\n')[0].strip()
            scored_results.append({
                "scene_name": scene_name,
                "score": float(score),
                "details": self.scene_data.get(scene_name, {}),
                "raw_content": doc
            })

        # 按分数降序排序
        scored_results.sort(key=lambda x: x["score"], reverse=True)

        # 去重并返回top_k
        seen = set()
        final_results = []
        for result in scored_results:
            if result["scene_name"] not in seen:
                seen.add(result["scene_name"])
                final_results.append(result)
                if len(final_results) >= top_k:
                    break

        return final_results


# 2. 定义 RAG 检索工具
@mcp.tool()
def rag_retrieve(query: str):
    """
    使用 RAG 检索模型进行场景检索。
    :param query: 用户查询内容
    :return: 检索到的相关场景列表
    """
    retriever = EnhancedScenarioRetriever()
    retriever.load_scenarios("knowledge.md")  # 这里可以替换成实际的路径
    retrieved_scenes = retriever.retrieve_scenes(query)

    # 格式化返回的场景信息
    response = []
    for scene in retrieved_scenes:
        response.append({
            "scene_name": scene['scene_name'],
            "score": scene['score'],
            "description": scene['details']['description'],
            "interface": scene['details']['interface'],
            "steps": scene['details']['steps']
        })
    return response


# 运行服务
if __name__ == '__main__':
    mcp.run()
