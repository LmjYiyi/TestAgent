from langchain_core.embeddings import Embeddings
from typing import List
import requests

# --- 自定义 SiliconFlow 嵌入类 ---
class SiliconFlowEmbeddings(Embeddings):
    def __init__(
        self,
        api_key: str,
        model_name: str = "BAAI/bge-large-zh-v1.5",
        api_base_url: str = "https://api.siliconflow.cn/v1",
        batch_size: int = 32,  # 根据 API 限制或性能进行调整
        request_timeout: int = 60,  # API 请求超时时间（秒）
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.api_url = f"{api_base_url}/embeddings"
        self.batch_size = batch_size
        self.request_timeout = request_timeout
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """嵌入单批文本。"""
        payload = {
            "model": self.model_name,
            "input": texts,  # API 文档建议 'input' 可以是字符串列表以进行批处理
            "encoding_format": "float",
        }

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                headers=self.headers,
                timeout=self.request_timeout,
            )
            response.raise_for_status()  # 针对 HTTP 错误引发异常
            response_data = response.json()

            if "data" in response_data and isinstance(response_data["data"], list):
                # 确保嵌入向量的顺序与输入文本的顺序相同
                # API 应该按顺序返回它们，但最好注意一下
                # 对于 BGE 模型，-large 版本的维度通常是 1024，-base 版本是 768
                # 如果可能，从第一个嵌入向量获取维度更安全，或者假设一个值
                # 对于 BAAI/bge-large-zh-v1.5，维度是 1024
                embeddings = [item["embedding"] for item in response_data["data"]]
                if len(embeddings) == len(texts):
                    return embeddings
                else:
                    print(
                        f"警告：收到的嵌入向量数量 ({len(embeddings)}) 与发送的文本数量 ({len(texts)}) 不匹配。"
                    )
                    # 后备方案：返回空嵌入向量或引发错误
                    return [[0.0] * 1024 for _ in texts]  # 占位符，调整维度
            else:
                print(f"错误：SiliconFlow API 返回了意外的响应格式：{response_data}")
                return [[0.0] * 1024 for _ in texts]  # 占位符

        except requests.exceptions.HTTPError as http_err:
            print(f"嵌入时发生 HTTP 错误：{http_err}")
            print(f"响应内容：{response.content.decode()}")
            return [[0.0] * 1024 for _ in texts]  # 占位符
        except requests.exceptions.Timeout:
            print(f"嵌入批处理时请求超时。")
            return [[0.0] * 1024 for _ in texts]  # 占位符
        except Exception as e:
            print(f"嵌入批处理时发生错误：{e}")
            return [[0.0] * 1024 for _ in texts]  # 占位符

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            print(
                f"正在嵌入批次 {i // self.batch_size + 1}/{(len(texts) -1) // self.batch_size + 1}，大小：{len(batch)}"
            )
            batch_embeddings = self._embed_batch(batch)
            all_embeddings.extend(batch_embeddings)
            # 可选：添加一个小延迟以避免达到速率限制（如果有）
            # time.sleep(0.1)
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        # 对于单个查询，API 期望 'input' 是一个字符串，而不是列表。
        payload = {
            "model": self.model_name,
            "input": text,
            "encoding_format": "float",
        }
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                headers=self.headers,
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            response_data = response.json()
            if (
                "data" in response_data
                and isinstance(response_data["data"], list)
                and len(response_data["data"]) > 0
            ):
                return response_data["data"][0]["embedding"]
            else:
                print(f"错误：查询的响应格式意外：{response_data}")
                return [0.0] * 1024  # 占位符，调整维度
        except requests.exceptions.HTTPError as http_err:
            print(f"嵌入查询时发生 HTTP 错误：{http_err}")
            print(f"响应内容：{response.content.decode()}")
            return [0.0] * 1024  # 占位符
        except requests.exceptions.Timeout:
            print(f"嵌入查询时请求超时。")
            return [0.0] * 1024  # 占位符
        except Exception as e:
            print(f"嵌入查询时发生错误：{e}")
            return [0.0] * 1024  # 占位符
