"""
本地向量服务实现（占位，未来实现）
当前阶段仅作为占位符，实际功能待实现
"""
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from .base_vector_service import BaseVectorService

logger = logging.getLogger(__name__)


class LocalVectorService(BaseVectorService):
    """本地向量服务（未来实现，使用本地嵌入模型）"""
    
    def _validate_config(self):
        """验证本地服务配置"""
        # TODO: 未来实现本地向量服务时，验证配置
        logger.warning("本地向量服务尚未实现，当前仅作为占位符")
    
    def embed_text(self, text: str, **kwargs) -> List[float]:
        """将文本转换为向量（待实现）"""
        logger.warning("本地向量服务尚未实现")
        raise NotImplementedError("本地向量服务正在开发中，请使用远程服务")
    
    def embed_batch(self, texts: List[str], **kwargs) -> List[List[float]]:
        """批量文本向量化（待实现）"""
        logger.warning("本地向量服务尚未实现")
        raise NotImplementedError("本地向量服务正在开发中，请使用远程服务")
    
    def embed_file(self, file_path: Path, **kwargs) -> Optional[List[float]]:
        """将文件内容转换为向量（待实现）"""
        logger.warning("本地向量服务尚未实现")
        return None
    
    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """向量相似度搜索（待实现）"""
        logger.warning("本地向量服务尚未实现")
        return []
    
    def add_document(
        self,
        doc_id: str,
        vector: List[float],
        metadata: Dict[str, Any],
        **kwargs
    ) -> bool:
        """添加文档向量到索引（待实现）"""
        logger.warning("本地向量服务尚未实现")
        return False
    
    def delete_document(self, doc_id: str, **kwargs) -> bool:
        """从索引中删除文档（待实现）"""
        logger.warning("本地向量服务尚未实现")
        return False
    
    def get_vector_dimension(self) -> int:
        """返回向量维度（待实现）"""
        return 384  # 默认值