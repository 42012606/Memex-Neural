"""
OpenAI 兼容 Provider 实现
支持 GPT-4, DeepSeek, MiMo (Xiaomi) 等兼容 OpenAI 接口的模型
"""
import logging
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from http import HTTPStatus

try:
    import openai
    from openai import OpenAI, APIError
except ImportError:
    openai = None
    OpenAI = None
    APIError = None

from .base_provider import BaseAIProvider

logger = logging.getLogger(__name__)

class OpenAIProvider(BaseAIProvider):
    """OpenAI 兼容模型提供者"""
    
    def __init__(self, api_key: str, model_id: str = None, **kwargs):
        self.client = None
        self.base_url = kwargs.get("base_url")
        # 如果没有指定 base_url 但 provider 是 openai，使用默认
        if not self.base_url and "openai" in self.__class__.__name__.lower():
            self.base_url = "https://api.openai.com/v1"
        
        # ✅ 保存预设配置（thinking, temperature 等），在 chat() 时自动应用
        self.preset_config = {k: v for k, v in kwargs.items() if k not in ['base_url']}
            
        super().__init__(api_key, model_id, **kwargs)
        
        # 再次确保初始化（虽然 _validate_config 可能已经调用过）
        if not self.client:
            self._init_client()

    def _init_client(self):
        """初始化 OpenAI Client"""
        if OpenAI is None:
            return
            
        if self.api_key:
            # 自动修复 Base URL: 移除末尾的 /chat/completions
            if self.base_url and self.base_url.endswith("/chat/completions"):
                self.base_url = self.base_url.replace("/chat/completions", "")
                
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
            logger.info(f"OpenAI Client initialized. BaseURL: {self.base_url}, Model: {self.model_id}")

    def get_default_model(self) -> str:
        return "gpt-4o"
    
    def _validate_config(self):
        """验证 OpenAI 配置"""
        if OpenAI is None:
            raise ImportError("请先安装 openai 库: pip install openai")
        
        if not self.api_key:
            raise ValueError("OpenAI API Key 不能为空")
            
        if not self.client:
            self._init_client()

    def _prepare_extra_body(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """准备 extra_body 参数，用于处理非标准参数（如 thinking）"""
        extra_body = {}
        
        # 处理 thinking 参数 (MiMo 特有)
        # 支持从 config 中直接传入 {"thinking": {"type": "enabled"}}
        if "thinking" in kwargs:
            extra_body["thinking"] = kwargs["thinking"]
        elif "thinking_type" in kwargs: #打平的参数支持
             extra_body["thinking"] = {"type": kwargs["thinking_type"]}
             
        return extra_body

    def chat(self, query: str, context: str = "", system_prompt: str = None, **kwargs) -> str:
        """
        聊天接口
        支持 OpenAI 兼容接口，支持 thinking mode
        """
        self._validate_config()

        # 1. 构建 System Prompt
        default_system_prompt = """
你是智能助手 Memex。
CORE RULES:
1. STRICT GROUNDING: 回答必须基于上下文信息。
2. NO EXTERNAL KNOWLEDGE FOR SPECIFICS: 不要编造具体数据。
3. CITATION: 尽可能引用来源。
"""
        final_system_prompt = system_prompt if system_prompt else default_system_prompt

        # 2. 构建 Messages
        messages = [
            {"role": "system", "content": final_system_prompt},
        ]
        
        if context:
            user_content = f"上下文信息:\n{context}\n\n用户问题: {query}"
        else:
            user_content = query
            
        messages.append({"role": "user", "content": user_content})

        # 3. 准备参数
        # 提取标准参数
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", kwargs.get("max_completion_tokens"))
        top_p = kwargs.get("top_p", 0.95)
        frequency_penalty = kwargs.get("frequency_penalty", 0)
        presence_penalty = kwargs.get("presence_penalty", 0)
        
        # ✅ 合并预设配置和调用时传入的参数
        merged_kwargs = {**self.preset_config, **kwargs}
        
        # 准备 extra_body (用于 thinking 等非标参数)
        extra_body = self._prepare_extra_body(merged_kwargs)
        
        # 记录是否启用了 thinking 模式
        if extra_body.get("thinking"):
            logger.info(f"🧠 Thinking mode enabled: {extra_body['thinking']}")

        try:
            # 4. 调用 API
            logger.info(f"━━━ PHASE 3: REASONING ━━━")
            logger.info(f"📤 Request: model={self.model_id}, thinking={bool(extra_body.get('thinking'))}")
            logger.debug(f"Params: temp={temperature}, extra_body={extra_body}")
            
            completion = self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_tokens, # OpenAI SDK v1.x uses max_completion_tokens for o1/newer models
                top_p=top_p,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
                stream=False, # 暂不支持流式，因 BaseProvider 接口限制
                extra_body=extra_body if extra_body else None
            )

            # 5. 处理响应
            choice = completion.choices[0]
            message = choice.message
            content = message.content or ""
            
            # 处理 Reasoning Content (思考过程)
            # MiMo/DeepSeek 可能在 message.reasoning_content 中返回
            reasoning_content = getattr(message, 'reasoning_content', None)
            
            if reasoning_content:
                logger.info(f"🧠 Thinking Process: {len(reasoning_content)} chars")
                if not content:
                    return f"[Thinking Process]\n{reasoning_content}"
            
            # ✅ 记录最终回复
            logger.info(f"✅ Response: {len(content)} chars")
            logger.info(f"━━━ PHASE 3: COMPLETE ━━━")
            
            return content

        except Exception as e:
            logger.error(f"OpenAI Chat request failed: {e}", exc_info=True)
            return f"AI Service Error: {str(e)}"

    def analyze_file(self, file_path: Path, context_text: str = None, **kwargs) -> Dict[str, Any]:
        """分析文件内容 (Review/Tagging)"""
        self._validate_config()
        
        file_name = file_path.name
        content_preview = context_text if context_text else f"文件名: {file_name}\n(无法提取直接文本)"
        if len(content_preview) > 30000:
            content_preview = content_preview[:30000] + "\n...(truncated)"
            
        # 复用 Dashscope 的 Prompt 逻辑，保持一致性
        import datetime
        now = datetime.datetime.now()
        file_ext = Path(file_name).suffix
        
        from src.core.prompt_manager import prompt_manager
        
        # Use simple default if DB is offline (rare)
        default_prompt = """
你是智能文件归档助手。请基于内容生成结构化 JSON。
**CRITICAL: You MUST include "suggested_filename" at the root.**

文件名: {filename}
内容预览:
{content_text}

**JSON Schema**:
{{
  "suggested_filename": "YYYYMMDD_核心内容摘要{file_ext}",
  "semantic": {{
    "category": "Medical/Finance/Work/Personal/Unsorted",
    "tags": ["tag1", "tag2"],
    "summary": "简短摘要（<=50字）"
  }},
  "structured": {{
    "date": "YYYY-MM-DD",
    "money": null
  }}
}}
"""
        prompt_template = prompt_manager.get("system.file_analyze", default=default_prompt)
        
        # Format the prompt using keyword arguments to match the template placeholders
        prompt = prompt_template.format(
            current_time=now.strftime("%Y-%m-%d %H:%M:%S"),
            filename=file_name,
            content_source="File Upload",
            content_text=content_preview,
            today_str=now.strftime("%Y%m%d"),
            file_ext=file_ext,
            now=now # For backward compat if template uses {now.year}
        )
        messages = [
            {"role": "system", "content": "You are a helpful assistant capable of JSON output."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            completion = self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                response_format={"type": "json_object"}, # 尝试强制 JSON
                temperature=0.1,
            )
            content = completion.choices[0].message.content
            
            # 简单的 JSON 解析与容错
            try:
                # 尝试提取 JSON 块
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    # 确保结构完整
                    if "semantic" not in data: data["semantic"] = {}
                    if "structured" not in data: data["structured"] = {}
                    return data
                else:
                    return {"semantic": {"summary": content[:100], "category": "Unsorted"}}
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON from OpenAI response: {content}")
                return {"semantic": {"summary": "Analysis failed (JSON Error)", "category": "Unsorted"}}
                
        except Exception as e:
            logger.error(f"OpenAI Analyze File failed: {e}")
            return {"semantic": {"summary": f"Error: {e}", "category": "Unsorted"}}

    def generate_text(self, prompt: str, **kwargs) -> str:
        """通用文本生成"""
        self._validate_config()
        try:
            completion = self.client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=kwargs.get("temperature", 0.7)
            )
            return completion.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI Generate Text failed: {e}")
            return f"Error: {str(e)}"
