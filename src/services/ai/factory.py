"""
AI Provider 工厂类
根据配置动态创建对应的 Provider 实例
"""
import logging
from typing import Optional, Dict, Any
from .base_provider import BaseAIProvider
from .gemini_provider import GeminiProvider
from .openai_provider import OpenAIProvider
from .dashscope_provider import DashscopeProvider

logger = logging.getLogger(__name__)


class AIProviderFactory:
    """AI 提供者工厂"""
    
    # 注册所有可用的 Provider
    _providers = {
        "gemini": GeminiProvider,
        "openai": OpenAIProvider,
        "dashscope": DashscopeProvider,
    }
    
    # 简单缓存：key -> instance
    _cache = {}

    @classmethod
    def create(
        cls,
        provider_type: str,
        api_key: str,
        model_id: Optional[str] = None,
        extra_config: Optional[Dict[str, Any]] = None,  # ✅ 新增参数
        **kwargs,
    ) -> BaseAIProvider:
        """
        创建 AI Provider 实例 (带缓存)
        :param provider_type: 提供者类型 (gemini/openai/dashscope)
        :param api_key: API 密钥
        :param model_id: 模型 ID（可选）
        :param extra_config: 额外配置参数（从数据库 config 字段读取）
        :return: Provider 实例
        """
        provider_type = provider_type.lower()
        
        # 1. 生成缓存 Key
        # 简单粗暴：Type + APIKey + ModelID
        # 注意：如果 kwargs 经常变，这里可能需要包含 kwargs
        cache_key = f"{provider_type}_{api_key}_{model_id}"
        
        if cache_key in cls._cache:
            # logger.debug(f"⚡ 使用缓存的 Provider: {provider_type} (model: {model_id})")
            return cls._cache[cache_key]

        if provider_type not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ValueError(
                f"不支持的 Provider 类型: {provider_type}。"
                f"可用类型: {available}"
            )
        
        provider_class = cls._providers[provider_type]
        
        # ✅ 合并 extra_config 到 kwargs
        if extra_config:
            kwargs.update(extra_config)
        
        try:
            instance = provider_class(api_key=api_key, model_id=model_id, **kwargs)
            logger.info(f"✅ 创建 {provider_type} Provider 成功 (model: {instance.model_id})")
            
            # 存入缓存
            cls._cache[cache_key] = instance
            
            return instance
        except Exception as e:
            logger.error(f"❌ 创建 {provider_type} Provider 失败: {e}")
            raise
    
    @classmethod
    def get_available_providers(cls) -> list:
        """返回所有可用的 Provider 类型列表"""
        return list(cls._providers.keys())