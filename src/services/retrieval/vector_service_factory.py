"""
向量服务工厂类
根据配置动态创建对应的向量服务实例
"""
import logging
from typing import Dict, Any
from .base_vector_service import BaseVectorService
from .remote_vector_service import RemoteVectorService
from .local_vector_service import LocalVectorService

logger = logging.getLogger(__name__)


class VectorServiceFactory:
    """向量服务工厂"""
    
    # 注册所有可用的向量服务类型
    _services = {
        "remote": RemoteVectorService,
        "local": LocalVectorService,
    }
    
    @classmethod
    def create(
        cls,
        service_type: str,
        config: Dict[str, Any]
    ) -> BaseVectorService:
        """
        创建向量服务实例
        :param service_type: 服务类型 (remote/local)
        :param config: 配置字典
        :return: 向量服务实例
        """
        service_type = service_type.lower()
        
        if service_type not in cls._services:
            available = ", ".join(cls._services.keys())
            raise ValueError(
                f"不支持的向量服务类型: {service_type}。"
                f"可用类型: {available}"
            )
        
        service_class = cls._services[service_type]
        
        try:
            instance = service_class(config)
            logger.info(f"✅ 创建 {service_type} 向量服务成功")
            return instance
        except Exception as e:
            logger.error(f"❌ 创建 {service_type} 向量服务失败: {e}")
            raise
    
    @classmethod
    def get_available_services(cls) -> list:
        """返回所有可用的向量服务类型列表"""
        return list(cls._services.keys())