from langchain_core.documents import BaseDocumentCompressor, Document
from collections.abc import Sequence
from langchain_core.callbacks import Callbacks
from typing import Any, Dict, List, Optional, Sequence, Union
from copy import deepcopy
import requests

class SiliconFlowRerank(BaseDocumentCompressor):
    api_key: str
    base_url: str = "https://api.siliconflow.cn/v1/rerank"
    model: Optional[str] = "BAAI/bge-reranker-v2-m3"
    top_n: Optional[int] = -1
    return_documents: Optional[bool] = False
    max_tokens_per_doc: Optional[int] = 1024
    overlap_tokens: Optional[int] = 80

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        compressed = []
        for res in self.rerank(documents, query):
            doc = documents[res["index"]]
            doc_copy = Document(doc.page_content, metadata=deepcopy(doc.metadata))
            doc_copy.metadata["relevance_score"] = res["relevance_score"]
            compressed.append(doc_copy)
        return compressed

    def rerank(
        self,
        documents: Sequence[Union[str, Document, dict]],
        query: str,
    ) -> List[Dict[str, Any]]:
        print("开始调用重排序")
        if len(documents) == 0:  # to avoid empty api call
            return []
        docs = [self._document_to_str(doc) for doc in documents]
        payload = {
            "model": self.model,
            "query": query,
            "documents": docs,
            "top_n": self.top_n,
            "return_documents": self.return_documents,
            "max_chunks_per_doc": self.max_tokens_per_doc,
            "overlap_tokens": self.overlap_tokens
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                self.base_url,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()  # 针对 HTTP 错误引发异常
            result = response.json()
        except requests.exceptions.HTTPError as http_err:
            print(f"重排序时发生 HTTP 错误：{http_err}")
            print(f"响应内容：{response.content.decode()}")
        except Exception as e:
            print(f"重排序时发生错误：{e}")

        result_dicts = []
        for res in result["results"]:
            result_dicts.append(
                {"index": res["index"], "relevance_score": res["relevance_score"]}
            )
        return result_dicts
    
    def _document_to_str(
        self,
        document: Union[str, Document, dict],
    ) -> str:
        if isinstance(document, Document):
            return document.page_content
        else:
            return document
