"""
向量服务抽象基类
定义统一的向量服务接口，支持本地/远程切换
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pathlib import Path


class BaseVectorService(ABC):
    """向量服务基类，所有具体实现必须继承此类"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化向量服务
        :param config: 配置字典（包含服务特定配置）
        """
        self.config = config
        self._validate_config()
    
    @abstractmethod
    def _validate_config(self):
        """验证配置是否有效"""
        pass
    
    @abstractmethod
    def embed_text(self, text: str, **kwargs) -> List[float]:
        """
        将文本转换为向量
        :param text: 输入文本
        :return: 向量列表（浮点数列表）
        """
        pass
    
    @abstractmethod
    def embed_batch(self, texts: List[str], **kwargs) -> List[List[float]]:
        """
        批量文本向量化
        :param texts: 文本列表
        :return: 向量列表的列表
        """
        pass
    
    @abstractmethod
    def embed_file(self, file_path: Path, **kwargs) -> Optional[List[float]]:
        """
        将文件内容转换为向量（多模态支持）
        :param file_path: 文件路径
        :return: 向量列表，如果文件类型不支持则返回 None
        """
        pass
    
    @abstractmethod
    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        向量相似度搜索
        :param query_vector: 查询向量
        :param top_k: 返回前 K 个结果
        :param filters: 过滤条件（例如：user_id, category 等）
        :return: 搜索结果列表，每个结果包含 id, score, metadata 等
        """
        pass
    
    @abstractmethod
    def add_document(
        self,
        doc_id: str,
        vector: List[float],
        metadata: Dict[str, Any],
        **kwargs
    ) -> bool:
        """
        添加文档向量到索引
        :param doc_id: 文档 ID（通常对应数据库记录 ID）
        :param vector: 文档向量
        :param metadata: 元数据（例如：filename, category, user_id 等）
        :return: 是否成功
        """
        pass
    
    @abstractmethod
    def delete_document(self, doc_id: str, **kwargs) -> bool:
        """
        从索引中删除文档
        :param doc_id: 文档 ID
        :return: 是否成功
        """
        pass
    
    @abstractmethod
    def get_vector_dimension(self) -> int:
        """返回向量维度"""
        pass