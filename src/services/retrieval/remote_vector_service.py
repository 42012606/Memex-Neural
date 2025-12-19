"""
远程向量服务实现
调用单位电脑的向量化服务（HTTP API）
"""
import logging
import requests
from typing import List, Dict, Any, Optional
from pathlib import Path
from .base_vector_service import BaseVectorService

logger = logging.getLogger(__name__)


class RemoteVectorService(BaseVectorService):
    """远程向量服务（调用单位电脑的向量化服务）"""
    
    def _validate_config(self):
        """验证远程服务配置"""
        remote_url = self.config.get("remote_url", "")
        if not remote_url:
            raise ValueError("远程向量服务 URL 未配置")
        
        # 确保 URL 以 / 结尾
        if not remote_url.endswith("/"):
            self.config["remote_url"] = remote_url + "/"
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头（包含 API Key）"""
        headers = {"Content-Type": "application/json"}
        api_key = self.config.get("remote_api_key", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers
    
    def _make_request(self, endpoint: str, method: str = "POST", data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        发送 HTTP 请求到远程服务
        :param endpoint: API 端点（例如 "embed"）
        :param method: HTTP 方法
        :param data: 请求数据
        :return: 响应数据
        """
        url = self.config["remote_url"] + endpoint
        headers = self._get_headers()
        
        try:
            if method == "POST":
                response = requests.post(url, json=data, headers=headers, timeout=30)
            elif method == "GET":
                response = requests.get(url, params=data, headers=headers, timeout=30)
            else:
                raise ValueError(f"不支持的 HTTP 方法: {method}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"远程向量服务请求失败: {e}")
            raise
    
    def embed_text(self, text: str, **kwargs) -> List[float]:
        """将文本转换为向量"""
        try:
            response = self._make_request("embed", data={"text": text})
            return response.get("vector", [])
        except Exception as e:
            logger.error(f"文本向量化失败: {e}")
            raise
    
    def embed_batch(self, texts: List[str], **kwargs) -> List[List[float]]:
        """批量文本向量化"""
        try:
            response = self._make_request("embed/batch", data={"texts": texts})
            return response.get("vectors", [])
        except Exception as e:
            logger.error(f"批量向量化失败: {e}")
            raise
    
    def embed_file(self, file_path: Path, **kwargs) -> Optional[List[float]]:
        """将文件内容转换为向量（多模态支持）"""
        try:
            # 读取文件并转换为 base64
            import base64
            with open(file_path, "rb") as f:
                file_data = base64.b64encode(f.read()).decode("utf-8")
            
            response = self._make_request("embed/file", data={
                "file_data": file_data,
                "filename": file_path.name,
                "mime_type": kwargs.get("mime_type", "")
            })
            return response.get("vector")
        except Exception as e:
            logger.warning(f"文件向量化失败（可能不支持该文件类型）: {e}")
            return None
    
    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """向量相似度搜索"""
        try:
            response = self._make_request("search", data={
                "query_vector": query_vector,
                "top_k": top_k,
                "filters": filters or {}
            })
            return response.get("results", [])
        except Exception as e:
            logger.error(f"向量搜索失败: {e}")
            return []
    
    def add_document(
        self,
        doc_id: str,
        vector: List[float],
        metadata: Dict[str, Any],
        **kwargs
    ) -> bool:
        """添加文档向量到索引"""
        try:
            response = self._make_request("add", data={
                "doc_id": doc_id,
                "vector": vector,
                "metadata": metadata
            })
            return response.get("success", False)
        except Exception as e:
            logger.error(f"添加文档向量失败: {e}")
            return False
    
    def delete_document(self, doc_id: str, **kwargs) -> bool:
        """从索引中删除文档"""
        try:
            response = self._make_request("delete", data={"doc_id": doc_id})
            return response.get("success", False)
        except Exception as e:
            logger.error(f"删除文档向量失败: {e}")
            return False
    
    def get_vector_dimension(self) -> int:
        """返回向量维度（从远程服务获取）"""
        try:
            response = self._make_request("info", method="GET")
            return response.get("vector_dimension", 384)  # 默认 384
        except Exception as e:
            logger.warning(f"获取向量维度失败，使用默认值: {e}")
            return 384