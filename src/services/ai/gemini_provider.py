"""
Google Gemini Provider 实现
"""
import json
import re
import logging
from pathlib import Path
from typing import Dict, Any
import google.generativeai as genai
import google.generativeai as genai
try:
    import PIL.Image
except ImportError:
    PIL = None
from .base_provider import BaseAIProvider

logger = logging.getLogger(__name__)


class GeminiProvider(BaseAIProvider):
    """Gemini 模型提供者"""
    
    def get_default_model(self) -> str:
        return "gemini-2.5-flash"
    
    def _validate_config(self):
        """验证 Gemini 配置"""
        if not self.api_key:
            raise ValueError("Gemini API Key 不能为空")
        try:
            # 强制使用 REST API 而非 gRPC，解决 Docker 代理环境下的 SSL 握手失败问题
            genai.configure(api_key=self.api_key, transport='rest')
        except Exception as e:
            raise ValueError(f"Gemini 配置失败: {e}")
    
    def _get_model(self):
        """获取模型实例"""
        return genai.GenerativeModel(self.model_id)
    
    def _clean_json_string(self, raw_text: str) -> str:
        """清洗 JSON 字符串（移除 Markdown 代码块）"""
        text = raw_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n", "", text)
            text = re.sub(r"\n```$", "", text)
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start: end + 1]
        return text
    
    def _is_pinyin_or_invalid_tag(self, tag: str) -> bool:
        """
        检测标签是否为拼音或无效格式（需丢弃）
        规则：
        1. 包含中文字符 -> 保留（返回 False）
        2. 常见英文单词 -> 保留（返回 False）
        3. 纯字母+下划线且长度>2 -> 可能是拼音，丢弃（返回 True）
        4. 包含数字但无中文 -> 可能是混合拼音，丢弃（返回 True）
        """
        if not isinstance(tag, str) or not tag.strip():
            return True
        
        tag = tag.strip()
        
        # 包含中文字符，保留
        if re.search(r'[\u4e00-\u9fff]', tag):
            return False
        
        # 常见英文单词（短词列表），保留
        common_words = {
            'report', 'file', 'doc', 'pdf', 'image', 'photo', 'video', 'audio',
            'medical', 'finance', 'work', 'personal', 'invoice', 'receipt',
            'contract', 'letter', 'email', 'note', 'memo', 'summary'
        }
        tag_lower = tag.lower().replace('_', '')
        if tag_lower in common_words or len(tag_lower) <= 3:
            return False
        
        # 纯字母+下划线，且长度>2，可能是拼音，丢弃
        if re.fullmatch(r'[A-Za-z_]+', tag) and len(tag.replace('_', '')) > 2:
            return True
        
        # 包含数字但无中文，可能是混合拼音，丢弃
        if re.search(r'\d', tag) and not re.search(r'[\u4e00-\u9fff]', tag):
            # 但如果是明显的日期格式（如 2024-01-01），保留
            if not re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}', tag):
                return True
        
        return False
    
    def analyze_file(self, file_path: Path, context_text: str = None, **kwargs) -> Dict[str, Any]:
        """
        分析文件内容
        :param file_path: 文件路径
        :param context_text: 提取的文本内容（OCR/转录结果），这是主要的内容来源
        :param kwargs: 其他可选参数
        """
        from datetime import datetime
        
        filename = file_path.name
        now = datetime.now()
        
        # 选择内容源：优先 OCR/转录文本，否则文件片段
        if context_text and context_text.strip():
            content_text = context_text[:4000]
            if len(context_text) > 4000:
                content_text += "..."
            content_source = "OCR/Transcript"
        else:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content_text = f.read(3000)
                content_source = "File Preview"
            except Exception:
                content_text = f"Binary File or Read Error: {filename}"
                content_source = "File Preview"

        # 提取文件扩展名
        file_ext = Path(filename).suffix
        
        # Task 3: 上下文时间注入 - 注入当前系统时间
        current_time = now.strftime('%Y-%m-%d %H:%M:%S')
        today_str = now.strftime("%Y%m%d")
        
        # [New] Use PromptManager for dynamic prompt
        from src.core.prompt_manager import prompt_manager
        template = prompt_manager.get("system.file_analyze")
        
        # Fallback if prompt is missing (unlikely if seeded)
        if not template:
            logger.error("❌ Critical: system.file_analyze prompt not found!")
            template = "Error: Prompt system.file_analyze missing."

        try:
            prompt = template.format(
                current_time=current_time,
                filename=filename,
                content_source=content_source,
                content_text=content_text,
                file_ext=file_ext,
                today_str=today_str
            )
        except KeyError as ke:
            logger.error(f"❌ Prompt formatting failed (missing key): {ke}")
            # Fallback to a simple prompt to avoid crash
            prompt = f"Analyze file: {filename}\nContent: {content_text}"
        
        try:
            model = self._get_model()
            response = model.generate_content(prompt)
            data = json.loads(self._clean_json_string(response.text))

            # 兜底字段
            semantic = data.get("semantic", {}) if isinstance(data, dict) else {}
            structured = data.get("structured", {}) if isinstance(data, dict) else {}
            suggested_filename = data.get("suggested_filename", "") if isinstance(data, dict) else ""
            
            data = {
                "semantic": {
                    "category": semantic.get("category", "Unsorted"),
                    "tags": semantic.get("tags", []),
                    "summary": semantic.get("summary", ""),
                },
                "structured": {
                    "date": structured.get("date", ""),
                    "money": structured.get("money"),
                },
                "suggested_filename": suggested_filename,
            }
            # 硬逻辑清洗：去掉拼音/下划线标签
            tags = data["semantic"].get("tags") or []
            clean_tags = []
            for t in tags:
                if not isinstance(t, str):
                    continue
                # 使用增强的拼音检测函数
                if self._is_pinyin_or_invalid_tag(t):
                    logger.warning(f"⚠️ 检测到拼音/无效标签，已丢弃: {t}")
                    continue
                clean_tags.append(t)
            data["semantic"]["tags"] = clean_tags
            return data
        except Exception as e:
            logger.error(f"Gemini Analyze Error: {e}")
            return {
                "semantic": {
                    "category": "Unsorted",
                    "tags": [],
                    "summary": "AI 处理失败，已原样归档",
                    "error": str(e),
                },
                "structured": {
                    "date": "",
                    "money": None,
                },
                "suggested_filename": "",
            }
    
    def recognize_image(self, image_url: str, **kwargs) -> str:
        """
        图片OCR识别/分析
        :param image_url: 图片本地路径
        """
        self._validate_config()
        if not image_url:
            return ""
            
        try:
            # 1. Load Prompt
            from src.core.prompt_manager import prompt_manager
            default_prompt = "Please describe this image in detail, extracting text and objects."
            prompt = prompt_manager.get("vision.analyze", default=default_prompt)

            # 2. Load Image
            if PIL is None:
                raise ImportError("Pillow (PIL) is not installed. Please install it to use Vision features.")
            
            try:
                img = PIL.Image.open(image_url)
            except Exception as e:
                logger.error(f"Gemini Load Image Failed: {e}")
                return f"Error loading image: {str(e)}"

            # 3. Call Model
            model = self._get_model()
            response = model.generate_content([prompt, img])
            
            # 4. Return Text
            return response.text
        except Exception as e:
            logger.error(f"Gemini Vision Error: {e}")
            raise e

    def chat(self, query: str, context: str = "", system_prompt: str = None, **kwargs) -> str:
        """
        聊天接口（Gemini 使用 prompt 而非消息列表，system_prompt 将被合并到 prompt 中）
        :param query: 用户问题
        :param context: 上下文信息
        :param system_prompt: 自定义系统提示（如果提供，将替换默认 Role/Goal）
        """
        try:
            # 如果提供了自定义系统提示，使用它；否则使用默认
            if system_prompt:
                role_section = system_prompt
            else:
                from src.core.prompt_manager import prompt_manager
                role_section = prompt_manager.get("system.chat_default")
                if not role_section:
                    role_section = "Role: Memex 数字助理\nGoal: 基于记忆回答问题。"
            
            prompt = f"""
            {role_section}
            
            【记忆片段】:
            {context}
            
            【用户问题】:
            "{query}"
            
            要求: 亲切、自然、中文回答。如果引用了文件，请用 **粗体** 标出文件名。
            """
            
            model = self._get_model()
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            from src.core.error_translator import translate_ai_error
            error_msg = translate_ai_error(str(e))
            logger.error(f"Gemini Chat Error: {error_msg}")
            return f"AI 思考时短路了: {error_msg}"
    
    def generate_text(self, prompt: str, **kwargs) -> str:
        """通用文本生成"""
        try:
            model = self._get_model()
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            from src.core.error_translator import translate_ai_error
            error_msg = translate_ai_error(str(e))
            logger.error(f"Gemini Generate Error: {error_msg}")
            return f"生成失败: {error_msg}"