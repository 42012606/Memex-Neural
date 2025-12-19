"""
AI Provider 抽象基类
定义统一的 AI 服务接口
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from pathlib import Path


class BaseAIProvider(ABC):
    """AI 提供者基类，所有具体实现必须继承此类"""
    
    def __init__(self, api_key: str, model_id: str = None, **kwargs):
        """
        初始化提供者
        :param api_key: API 密钥
        :param model_id: 模型 ID（可选，由子类决定默认值）
        """
        self.api_key = api_key
        self.model_id = model_id or self.get_default_model()
        self._validate_config()
    
    @abstractmethod
    def get_default_model(self) -> str:
        """返回该提供者的默认模型 ID"""
        pass
    
    @abstractmethod
    def _validate_config(self):
        """验证配置是否有效"""
        pass
    
    @abstractmethod
    def analyze_file(self, file_path: Path, context_text: str = None, **kwargs) -> Dict[str, Any]:
        """
        分析文件内容
        :param file_path: 文件路径
        :param context_text: 可选，提取的文本内容（OCR/转录结果），用于帮助 AI 理解文件内容
        :param kwargs: 其他可选参数
        :return: 包含 summary, category, subcategory, confidence 等的字典
        """
        pass
    
    @abstractmethod
    def chat(self, query: str, context: str = "", **kwargs) -> str:
        """
        聊天接口（支持 RAG）
        :param query: 用户问题
        :param context: 上下文信息
        :return: AI 回复文本
        """
        pass
    
    @abstractmethod
    def generate_text(self, prompt: str, **kwargs) -> str:
        """
        通用文本生成
        :param prompt: 提示词
        :return: 生成的文本
        """
        pass