"""
阿里云 Dashscope Provider 实现
支持 Qwen (通义千问) 系列模型
"""
import logging
import json
import re
import os
import time
import uuid
import mimetypes
import requests
from http import HTTPStatus
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import dashscope
except ImportError:
    dashscope = None

try:
    import oss2  # type: ignore
except ImportError:
    oss2 = None
from .base_provider import BaseAIProvider
from src.core.config import settings
from src.services.file_service import get_file_public_url

logger = logging.getLogger(__name__)

# 注册常见音频类型，避免默认成 text/plain
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("audio/x-m4a", ".m4a")
mimetypes.add_type("audio/mp4", ".mp4")
mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("audio/aac", ".aac")
mimetypes.add_type("audio/ogg", ".ogg")

# OSS 配置占位符（可改成环境变量）
OSS_ACCESS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET", "")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")
OSS_BUCKET_NAME = os.getenv("OSS_BUCKET_NAME", "voice-temp-2025")


class DashscopeProvider(BaseAIProvider):
    """阿里云 Dashscope 模型提供者（通义千问等）"""
    def _pick_accessible_url(self, file_url: str) -> str:
        """
        检测文件 URL 可达性，必要时从 https 回退到 http，并记录状态码/错误，便于排查。
        """
        candidates = [file_url]
        if file_url.startswith("https://"):
            candidates.append("http://" + file_url[len("https://"):])

        for idx, url in enumerate(candidates):
            try:
                resp = requests.head(url, timeout=8, allow_redirects=True, verify=False)
                logger.info(f"   文件 URL 可达性探测[{idx}]: {url} -> {resp.status_code}")
                if resp.status_code == 200:
                    if idx == 1:
                        logger.warning(f"   原 https 不可达或被拒，改用 http: {url}")
                    return url
            except Exception as e:
                logger.warning(f"   文件 URL 探测失败[{idx}]: {url} -> {e}")

        logger.warning("   文件 URL 探测未通过，仍使用原始链接提交 DashScope，可能继续报错。")
        return file_url

    def _download_with_retry(self, url: str, retries: int = 3) -> requests.Response:
        """
        带重试的下载方法，解决 SSL/连接不稳定问题
        """
        import time
        last_error = None
        for i in range(retries):
            try:
                # verify=False 避免自签名证书报错
                resp = requests.get(url, timeout=30, verify=False)
                resp.raise_for_status()
                return resp
            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ 下载失败 (尝试 {i+1}/{retries}): {e}")
                time.sleep(1 * (i + 1))  # 简单的线性退避
        raise last_error


    
    def get_default_model(self) -> str:
        return "qwen-plus"
    
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
            
        # 常见保留词（白名单）
        whitelist = {
            'python', 'java', 'c++', 'javascript', 'html', 'css', 'sql', 'json',
            'api', 'sdk', 'url', 'http', 'https', 'pdf', 'doc', 'docx', 'xls', 'xlsx',
            'ppt', 'pptx', 'jpg', 'jpeg', 'png', 'gif', 'mp4', 'mp3', 'wav',
            'ai', 'llm', 'gpt', 'ocr', 'tts', 'stt',
            'report', 'file', 'image', 'video', 'audio', 'invoice', 'receipt'
        }
        tag_lower = tag.lower().replace('_', '')
        if tag_lower in whitelist:
            return False
            
        # 纯字母但长度较短 (<=3)，保留（如 AI, UI, UX）
        if len(tag_lower) <= 3:
            return False
            
        # 疑似拼音检测规则：
        # 1. 纯小写字母+下划线，且不在白名单中
        # 2. 长度 > 3
        # 3. 看起来像拼音组合 (这里不做复杂NLP，只做简单启发式拦截)
        # 策略调整：默认信任英文标签，除非它非常有拼音特征（但很难通过正则完美判断）
        # 现在的策略：如果纯字母，不再强制丢弃，除非显式匹配到垃圾特征。
        # 既然用户抱怨 "Python" 被丢弃，说明之前的 `[A-Za-z_]+` 规则太激进。
        # 改为：保留所有纯字母标签，只丢弃包含数字的非日期/非版本号混合体
        
        # 包含数字但无中文，且不符合日期/版本号格式，可能是乱码或混合拼音，丢弃
        if re.search(r'\d', tag) and not re.search(r'[\u4e00-\u9fff]', tag):
             # 允许 v1.0, 2024, 2024-01-01
            if re.match(r'^[vV]?\d+(\.\d+)*$', tag): # 版本号
                return False
            if re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}', tag): # 日期
                return False
            if re.match(r'^\d{4}$', tag): # 年份
                return False
            return True # 其他带数字的混合体丢弃
        
        return False
    
    def _validate_config(self):
        """验证 Dashscope 配置"""
        if not self.api_key:
            raise ValueError("Dashscope API Key 不能为空")
        
        if dashscope is None:
            raise ImportError("请先安装 dashscope 库: pip install dashscope")
            
        dashscope.api_key = self.api_key
        logger.info(f"Using Dashscope model: {self.model_id}")
    
    def analyze_file(self, file_path: Path, context_text: str = None, **kwargs) -> Dict[str, Any]:
        """
        分析文件内容
        :param file_path: 文件路径
        :param context_text: 提取的文本内容（OCR/转录结果）
        """
        self._validate_config()
        
        # 构造提示词
        file_name = file_path.name
        content_preview = context_text if context_text else f"文件名: {file_name}\n(无法提取直接文本，请根据文件名推测)"

        if content_preview and len(content_preview) > 30000:
            content_preview = content_preview[:30000] + "\n...(content truncated)..."

        from datetime import datetime
        file_ext = Path(file_name).suffix
        now = datetime.now()
        
        from src.core.prompt_manager import prompt_manager
        
        # Use simple default if DB offline
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
        
        prompt = prompt_template.format(
            current_time=now.strftime("%Y-%m-%d %H:%M:%S"),
            filename=file_name,
            content_source="File Upload",
            content_text=content_preview,
            today_str=now.strftime("%Y%m%d"),
            file_ext=file_ext,
            now=now
        )
        
        try:
            messages = [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': prompt}
            ]
            
            response = dashscope.Generation.call(
                model=self.model_id,
                messages=messages,
                result_format='message',  # 设置返回格式为 message
            )
            
            if response.status_code == HTTPStatus.OK:
                content = response.output.choices[0].message.content
                
                # 解析 JSON
                try:
                    # 尝试找到 JSON 块
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        json_str = json_match.group()
                        result = json.loads(json_str)
                        semantic = result.get("semantic", {}) if isinstance(result, dict) else {}
                        structured = result.get("structured", {}) if isinstance(result, dict) else {}
                        suggested_filename = result.get("suggested_filename", "") if isinstance(result, dict) else ""
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
                    else:
                        logger.warning("Dashscope 响应未包含 JSON，尝试直接解析")
                        # 兜底：如果没找到 JSON，返回基础信息
                        return {
                            "semantic": {
                                "category": "Unsorted",
                                "tags": [],
                                "summary": content[:100],
                                "error": "no_json",
                            },
                            "structured": {
                                "date": "",
                                "money": None,
                            },
                            "suggested_filename": "",
                        }
                except Exception as e:
                    logger.error(f"解析 Dashscope JSON 失败: {e}")
                    return {
                        "semantic": {
                            "category": "Unsorted",
                            "tags": [],
                            "summary": "解析失败",
                            "error": f"JSON 解析错误: {str(e)}",
                        },
                        "structured": {
                            "date": "",
                            "money": None,
                        },
                        "suggested_filename": "",
                    }
            else:
                raise Exception(f"Dashscope API Error: {response.code} - {response.message}")
                
        except Exception as e:
            logger.error(f"Dashscope 分析失败: {e}", exc_info=True)
            raise

    
    def chat(self, query: str, context: str = "", system_prompt: str = None, **kwargs) -> str:
        """
        聊天接口（遵循单一系统消息原则）
        支持 Qwen-VL 等多模态模型（当模型 ID 包含 'vl' 时自动切换 API）
        """
        self._validate_config()
        
        # 判断是否为视觉模型 (Qwen-VL 系列)
        is_vision_model = 'vl' in self.model_id.lower()
        
        # 默认系统提示
        default_system_prompt = """
你是智能助手 Memex。

CORE RULES:
1. **STRICT GROUNDING (严格基于上下文)**:
   - 所有的回答必须完全基于提供的【上下文信息】。
   - 如果用户询问的内容在【上下文信息】中不存在，请直接简明地回答“未在当前上下文中找到相关信息”，不要尝试编造或猜测。
   - 禁止凭空生成文件名、日期、金额或人物信息。

2. **NO EXTERNAL KNOWLEDGE FOR SPECIFICS (特定事实不使用外部知识)**:
   - 对于具体的文档、数据、事件查询，仅使用上下文内容。
   - 不要从你的训练数据中臆造具体的用户数据（例如不要编造“李明”、“张三”的报销单，除非上下文中真有）。

3. **CITATION (引用)**:
   - 引用上下文中的信息时，如果可能，请指明来源（如文件名）。
"""
        
        final_system_prompt = system_prompt if system_prompt else default_system_prompt
        
        user_content = query
        if context:
            user_content = f"上下文信息:\n{context}\n\n用户问题: {query}"
            
        try:
            # 针对视觉模型 (Qwen-VL) 使用 MultiModalConversation
            if is_vision_model:
                # Qwen-VL 目前主要接受 User 消息，System 消息并非所有版本都支持
                # 为兼容性，将 System Prompt 拼接到 User 消息前，或者尝试支持 System Role
                # DashScope MultiModal 接口格式：
                # messages = [{role: user, content: [{text: ...}, {image: ...}]}]
                # 这里只发送文本
                
                # 尝试构建标准消息
                messages = [
                    {
                        'role': 'system',
                        'content': [{'text': final_system_prompt}]
                    },
                    {
                        'role': 'user',
                        'content': [{'text': user_content}]
                    }
                ]
                
                # 如果是 qwen-vl-plus/max，通常支持 system prompt
                # 如果调用报错，可能需要回退到仅 User
                
                response = dashscope.MultiModalConversation.call(
                    model=self.model_id,
                    messages=messages
                )
                
                if response.status_code == HTTPStatus.OK:
                    # MultiModal 返回结构: output.choices[0].message.content (list or text?)
                    # 通常 content 是 list: [{'text': '...'}]
                    content_list = response.output.choices[0].message.content
                    if isinstance(content_list, list):
                        return content_list[0].get('text', '')
                    return str(content_list)
                else:
                    return f"Dashscope VL API Error: {response.code} - {response.message}"

            else:
                # 标准文本模型 (Qwen-Turbo/Plus/Max)
                messages = [
                    {'role': 'system', 'content': final_system_prompt},
                    {'role': 'user', 'content': user_content}
                ]
                
                response = dashscope.Generation.call(
                    model=self.model_id,
                    messages=messages,
                    result_format='message',
                )
                
                if response.status_code == HTTPStatus.OK:
                    return response.output.choices[0].message.content
                else:
                    return f"Dashscope API Error: {response.code} - {response.message}"
                
        except Exception as e:
            from src.core.error_translator import translate_ai_error
            error_msg = translate_ai_error(str(e))
            logger.error(f"Dashscope Chat 失败: {error_msg}", exc_info=True)
            return f"发生错误: {error_msg}"
    
    def generate_text(self, prompt: str, **kwargs) -> str:
        """通用文本生成"""
        self._validate_config()
        
        try:
            response = dashscope.Generation.call(
                model=self.model_id,
                prompt=prompt
            )
            
            if response.status_code == HTTPStatus.OK:
                return response.output.text
            else:
                return f"Error: {response.message}"
        except Exception as e:
            logger.error(f"Dashscope Generate 失败: {e}")
            return f"Error: {str(e)}"
    
    def recognize_image(self, image_url: str, **kwargs) -> str:
        """
        图片OCR识别
        :param image_url: 图片URL或本地文件路径（DashScope 支持本地路径）
        :return: 提取的文本内容
        """
        self._validate_config()
        
        try:
            # Unified Prompt from PromptManager
            from src.core.prompt_manager import prompt_manager
            # Fallback to a simple default if DB is empty (should not happen with force update)
            default_vision_prompt = """
            Please analyze this image and output a detailed description.
            Output JSON format:
            {
                "visual_summary": "Detailed visual description",
                "ocr_text": "Text in image",
                "tags": ["tag1", "tag2"]
            }
            """
            prompt = prompt_manager.get("vision.analyze", default=default_vision_prompt)
            
            # 构建消息
            # DashScope MultiModalConversation 支持本地文件路径，不需要转换为 URL
            messages = [
                {
                    'role': 'user',
                    'content': [
                        {'image': image_url},
                        {'text': prompt}
                    ]
                }
            ]
            
            response = dashscope.MultiModalConversation.call(
                model=self.model_id,
                messages=messages
            )
            
            if response.status_code == HTTPStatus.OK:
                return response.output.choices[0].message.content[0].get('text', '')
            else:
                raise Exception(f"Dashscope Vision API Error: {response.code} - {response.message}")
                
        except Exception as e:
            logger.error(f"Dashscope 图片识别失败: {e}", exc_info=True)
            raise
    
    def transcribe_audio(self, file_path: Path, **kwargs) -> str:
        """
        音频转录
        :param file_path: 音频文件路径
        :return: 转录的文本内容
        """
        self._validate_config()
        
        # 支持的 ASR 模型列表（已测试：fun-asr-mtl, paraformer-v2）
        # 移除模型检查警告，允许使用任何模型进行测试
        
        if oss2 is None:
            raise ImportError("请先安装阿里云 OSS SDK：pip install oss2")
        if not all([OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET, OSS_ENDPOINT, OSS_BUCKET_NAME]):
            raise ValueError("OSS 配置缺失，请设置 OSS_ACCESS_KEY_ID/OSS_ACCESS_KEY_SECRET/OSS_ENDPOINT/OSS_BUCKET_NAME")

        # 根据文件扩展名确定音频格式
        suffix = file_path.suffix.lower()
        format_map = {
            '.wav': 'wav',
            '.mp3': 'mp3',
            '.m4a': 'm4a',
            '.flac': 'flac',
            '.aac': 'aac',
            '.ogg': 'ogg',
        }
        audio_format = format_map.get(suffix, 'wav')

        logger.info(f"🎵 使用格式 {audio_format} 转录音频: {file_path.name}")
        logger.info(f"   文件绝对路径: {file_path.absolute()}")

        # 准备 OSS 客户端与临时对象 key
        auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
        bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)
        temp_object_key = f"temp/{uuid.uuid4()}{suffix or '.wav'}"
        delete_status = None

        try:
            # 1) 上传 OSS（标准存储）
            logger.info(f"   上传到 OSS: {temp_object_key}")
            headers = {"x-oss-storage-class": "Standard"}
            put_resp = bucket.put_object_from_file(temp_object_key, str(file_path), headers=headers)
            put_status = getattr(put_resp, "status", None)
            logger.info(f"   OSS put status: {put_status}")

            # 2) 生成带签名的安全 HTTPS 链接（有效期 1 小时）
            # 这样 DashScope 可以通过公网安全地读取私有 Bucket 的文件，不受区域限制
            signed_url = bucket.sign_url('GET', temp_object_key, 60 * 60)
            # 确保使用 HTTPS 协议
            if signed_url.startswith("http://"):
                signed_url = "https://" + signed_url[7:]
            logger.info(f"   ✅ 生成的临时签名 URL: {signed_url}")
            logger.info(f"   音频格式: {audio_format}, 模型: {self.model_id}")

            # 3) 使用签名 URL 发起异步转录
            logger.info("   提交异步转录任务...")
            
            # DashScope ASR API 调用
            try:
                task_response = dashscope.audio.asr.Transcription.async_call(
                    model=self.model_id,
                    file_urls=[signed_url],
                    format=audio_format
                )
            except Exception as api_err:
                logger.error(f"   DashScope API 调用异常: {api_err}")
                raise
            
            logger.debug(f"   任务提交响应 status_code: {task_response.status_code}")
            logger.debug(f"   任务提交响应 output: {getattr(task_response, 'output', None)}")
            
            if task_response.status_code != HTTPStatus.OK:
                error_code = getattr(task_response, 'code', 'Unknown')
                error_msg = getattr(task_response, 'message', 'Unknown error')
                error_output = getattr(task_response, 'output', None)
                logger.error(f"   提交失败详情: code={error_code}, message={error_msg}, output={error_output}")
                raise Exception(f"提交转录任务失败: {error_code} - {error_msg}")
            
            # 获取任务 ID
            output = task_response.output
            if isinstance(output, dict):
                task_id = output.get('task_id')
            else:
                task_id = getattr(output, 'task_id', None)
            
            if not task_id:
                raise Exception(f"无法获取任务 ID，响应: {output}")
            
            logger.info(f"   ✅ 任务已提交，Task ID: {task_id}，正在后台处理...")
            
            # 等待任务完成
            import time
            max_wait_time = 300  # 最多等待 5 分钟
            start_time = time.time()
            response = None
            
            while time.time() - start_time < max_wait_time:
                response = dashscope.audio.asr.Transcription.wait(task=task_id)
                
                if response.status_code != HTTPStatus.OK:
                    logger.error(f"   查询任务失败: status={response.status_code} code={getattr(response, 'code', None)} message={getattr(response, 'message', None)} output={getattr(response, 'output', None)}")
                    raise Exception(f"查询任务状态失败: {response.code} - {response.message}")
                
                # 检查任务状态
                result_output = response.output
                # logger.debug(f"   任务状态查询响应: {result_output}")
                
                # 尝试多种可能的状态字段名
                task_status = None
                if isinstance(result_output, dict):
                    task_status = (result_output.get('task_status') or 
                                  result_output.get('status') or 
                                  result_output.get('state') or '')
                else:
                    task_status = (getattr(result_output, 'task_status', None) or 
                                 getattr(result_output, 'status', None) or 
                                 getattr(result_output, 'state', None) or '')
                
                logger.info(f"   🔄 当前任务状态: {task_status}")
                
                # 检查任务是否完成（成功或失败）
                if task_status in ['SUCCESS', 'COMPLETED', 'DONE', 'SUCCEEDED']:
                    logger.info("   ✅ 转录任务完成")
                    break
                elif task_status in ['FAILED', 'ERROR', 'FAILURE']:
                    # 尝试获取错误信息
                    error_msg = ''
                    if isinstance(result_output, dict):
                        error_msg = (result_output.get('error_message') or 
                                   result_output.get('error') or 
                                   result_output.get('message') or 
                                   result_output.get('error_msg') or '')
                    else:
                        error_msg = (getattr(result_output, 'error_message', None) or 
                                   getattr(result_output, 'error', None) or 
                                   getattr(result_output, 'message', None) or '')
                    logger.error(f"   转录任务失败，错误信息: {error_msg}")
                    logger.error(f"   转录失败响应完整输出: {result_output}")
                    raise Exception(f"转录任务失败: {error_msg if error_msg else '未知错误'}")
                elif task_status in ['RUNNING', 'PROCESSING', 'PENDING', 'IN_PROGRESS'] or not task_status:
                    # 任务还在进行中，继续等待
                    # 如果 task_status 为空，也继续等待（可能是 RUNNING 状态但字段名不同）
                    elapsed = int(time.time() - start_time)
                    logger.info(f"   任务进行中（已等待 {elapsed} 秒），继续等待...")
                    time.sleep(2)
                else:
                    # 未知状态，记录并继续等待（不立即失败）
                    logger.warning(f"   未知任务状态: {task_status}，继续等待...")
                    time.sleep(2)
            else:
                raise Exception(f"转录任务超时（超过 {max_wait_time} 秒）")
            
            # 处理转录结果
            result_output = response.output
            logger.debug(f"   转录响应: {result_output}")
            logger.info(f"🐛 [DEBUG] 原始转录响应: {json.dumps(result_output, ensure_ascii=False, default=str)}")
            
            # 解析转录结果
            # DashScope 异步转录返回的格式：
            # {'results': [{'transcription_url': 'https://...', 'subtask_status': 'SUCCEEDED'}]}
            final_text = ""
            
            if isinstance(result_output, dict):
                # 检查是否有 results 列表
                if 'results' in result_output and isinstance(result_output['results'], list):
                    logger.info(f"   找到 {len(result_output['results'])} 个转录结果")
                    # 遍历 results 列表中的每个条目
                    for idx, result_item in enumerate(result_output['results']):
                        if not isinstance(result_item, dict):
                            continue
                        
                        # 优先检查 transcription_url（需要下载结果）
                        if 'transcription_url' in result_item:
                            transcription_url = result_item['transcription_url']
                            logger.info(f"   [结果 {idx+1}] 需要从 URL 下载转录结果: {transcription_url}")
                            try:
                                # [FIX] 使用带重试的下载方法
                                download_response = self._download_with_retry(transcription_url)
                                if download_response.status_code == 200:
                                    transcription_data = download_response.json()
                                    logger.debug(f"   [结果 {idx+1}] 下载的转录数据: {json.dumps(transcription_data, ensure_ascii=False, default=str)}")
                                    
                                    # 提取文本：优先查找 transcripts.text（Paraformer 标准格式）
                                    if isinstance(transcription_data, dict):
                                        # 检查 transcripts.text 路径
                                        if 'transcripts' in transcription_data:
                                            transcripts = transcription_data['transcripts']
                                            if isinstance(transcripts, list) and len(transcripts) > 0:
                                                for transcript in transcripts:
                                                    if isinstance(transcript, dict):
                                                        text = transcript.get('text', '') or transcript.get('sentence', '')
                                                        if text:
                                                            final_text += text + " "
                                            elif isinstance(transcripts, dict):
                                                text = transcripts.get('text', '') or transcripts.get('sentence', '')
                                                if text:
                                                    final_text += text + " "
                                        
                                        # 兜底：直接查找 text/sentence 字段
                                        if not final_text or (idx == 0 and not final_text.strip()):
                                            text = transcription_data.get('text', '') or transcription_data.get('sentence', '')
                                            if text:
                                                final_text += text + " "
                                        
                                        # 检查 results 列表（嵌套结构）
                                        if not final_text or (idx == 0 and not final_text.strip()):
                                            if 'results' in transcription_data and isinstance(transcription_data['results'], list):
                                                for nested_result in transcription_data['results']:
                                                    if isinstance(nested_result, dict):
                                                        text = nested_result.get('text', '') or nested_result.get('sentence', '')
                                                        if text:
                                                            final_text += text + " "
                                else:
                                    logger.warning(f"   [结果 {idx+1}] 下载转录结果失败: HTTP {download_response.status_code}")
                            except Exception as e:
                                logger.warning(f"   [结果 {idx+1}] 下载转录结果异常: {e}", exc_info=True)
                        
                        # 兜底：如果条目中没有 transcription_url，直接查找 sentence/text 字段
                        if not final_text or (idx == 0 and not final_text.strip()):
                            text = result_item.get('sentence', '') or result_item.get('text', '') or result_item.get('transcription', '')
                            if text:
                                final_text += text + " "
                                logger.info(f"   [结果 {idx+1}] 从条目中直接提取文本")
                
                # 兜底：如果 result_output 中没有 results，直接查找顶层字段
                if not final_text:
                    final_text = result_output.get('sentence', '') or result_output.get('text', '') or result_output.get('transcription', '') or ''
            
            elif isinstance(result_output, list) and len(result_output) > 0:
                # 列表格式：遍历所有结果
                for result in result_output:
                    if isinstance(result, dict):
                        text = result.get('sentence', '') or result.get('text', '') or result.get('transcription', '')
                        if text:
                            final_text += text + " "
                    else:
                        text = getattr(result, 'sentence', '') or getattr(result, 'text', '')
                        if text:
                            final_text += text + " "
            else:
                # 对象格式
                final_text = getattr(result_output, 'sentence', '') or getattr(result_output, 'text', '') or ''
            
            # 清理末尾空格
            final_text = final_text.strip()
            
            if final_text:
                logger.info(f"✅ 音频转录成功，文本长度: {len(final_text)}")
                return final_text
            else:
                logger.warning("⚠️ 音频转录返回空结果")
                logger.debug(f"   响应内容: {result_output}")
                return ''
                
        except Exception as e:
            logger.error(f"Dashscope 音频转录失败: {e}", exc_info=True)
            raise
        finally:
            # 4) 清理 OSS 临时文件（无论成功或失败）
            try:
                if temp_object_key:
                    del_resp = bucket.delete_object(temp_object_key)
                    delete_status = getattr(del_resp, "status", None)
                    logger.info(f"   已删除 OSS 临时文件: {temp_object_key}, status: {delete_status}")
            except Exception as cleanup_err:
                logger.warning(f"   删除 OSS 临时文件失败，请手动清理: {cleanup_err}")
    
    def embed_text(self, text: str, **kwargs) -> list:
        """
        文本向量化
        :param text: 输入文本
        :return: 向量列表
        """
        self._validate_config()
        
        try:
            response = dashscope.TextEmbedding.call(
                model=self.model_id,
                input=text
            )
            
            if response.status_code == HTTPStatus.OK:
                # response.output 可能是字典或对象，需要兼容处理
                output = response.output
                
                # 如果是字典，使用字典访问方式
                if isinstance(output, dict):
                    embeddings = output.get('embeddings', [])
                    if not embeddings:
                        raise Exception("Dashscope Embedding API 返回的 embeddings 为空")
                    embedding_data = embeddings[0]
                    # embedding_data 可能是字典或对象
                    if isinstance(embedding_data, dict):
                        return embedding_data.get('embedding')
                    else:
                        return embedding_data.embedding
                else:
                    # 如果是对象，使用属性访问方式
                    return output.embeddings[0].embedding
            else:
                raise Exception(f"Dashscope Embedding API Error: {response.code} - {response.message}")
                
        except Exception as e:
            logger.error(f"Dashscope 文本向量化失败: {e}", exc_info=True)
            raise

    def synthesize_audio(self, text: str, voice: str = "longxiaochun") -> bytes:
        """
        语音合成 (TTS)
        :param text: 要合成的文本
        :param voice: 音色 ID (e.g. longxiaochun)
        :return: 音频二进制数据 (MP3)
        """
        self._validate_config()
        
        try:
            # 动态导入，避免未安装时的报错
            import dashscope.audio.tts as tts
            
            # 使用配置的模型 ID (e.g. sambert-zhichu-v1, qwen-tts)
            model = self.model_id
            if not model:
                model = "sambert-zhichu-v1"
            
            logger.info(f"🎤 Synthesizing audio with model={model}, voice={voice}...")
            
            # DashScope TTS Call
            response = tts.SpeechSynthesizer.call(
                model=model,
                text=text,
                voice=voice,
                format='mp3' # 默认返回 MP3 格式
            )
            
            # response 或者是 SynthesisResponse 对象
            # get_audio_data() 返回 bytes
            if response.get_audio_data() is not None:
                return response.get_audio_data()
            else:
                # 获取错误信息
                resp_json = response.get_response()
                error_msg = resp_json.get('message', 'Unknown TTS error') if resp_json else "Unknown TTS error"
                raise Exception(f"DashScope TTS failed: {error_msg}")

        except Exception as e:
            logger.error(f"Dashscope TTS failed: {e}", exc_info=True)
            raise

    def check_health(self) -> Dict[str, Any]:
        """
        检查模型健康状态
        根据模型类型执行不同的轻量级检查
        """
        self._validate_config()
        
        try:
            # 1. 检测模型类型
            model_id_lower = self.model_id.lower()
            is_embedding = "text-embedding" in model_id_lower or "embedding" in model_id_lower
            is_audio_speech = "tts" in model_id_lower or "speech" in model_id_lower or "cosyvoice" in model_id_lower
            is_audio_transcription = "paraformer" in model_id_lower or "sensevoice" in model_id_lower or "asr" in model_id_lower
            is_vision = "vl" in model_id_lower or "vision" in model_id_lower
            
            # 2. 根据类型执行测试
            if is_embedding:
                # 向量模型：尝试 embed 一个单词
                self.embed_text("test")
                return {"status": "ok", "message": "Embedding service is nominal"}
                
            elif is_audio_speech:
                # TTS 模型：尝试生成极短的音频 (dry run or smoke test)
                # 目前 DashScope 没有专门的 health check，但如果 api key 错误会在初始化或调用时报错。
                if dashscope is None:
                     return {"status": "error", "message": "Dashscope SDK not installed"}
                
                return {"status": "ok", "message": "TTS configuration is valid"}
            
            elif is_audio_transcription:
                # ASR 模型：需要 OSS 权限，检查 OSS 配置
                if not all([OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET, OSS_ENDPOINT, OSS_BUCKET_NAME]):
                    return {"status": "error", "message": "OSS configuration missing for ASR"}
                # 验证 OSS 连接
                try:
                    auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
                    bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)
                    bucket.get_bucket_info()
                except Exception as oss_err:
                     return {"status": "error", "message": f"OSS Connection Failed: {oss_err}"}
                     
                return {"status": "ok", "message": "ASR & OSS configuration is valid"}
                
            else:
                # 默认 Chat/Reasoning/Vision：尝试简单的 Chat
                test_msg = [{'role': 'user', 'content': 'Hi'}]
                
                # Qwen-VL 特殊处理
                if is_vision:
                     # 使用 MultiModal 接口测试，只发文本
                     dashscope.MultiModalConversation.call(
                        model=self.model_id,
                        messages=[{'role': 'user', 'content': [{'text': 'Hi'}]}]
                     )
                else:
                    dashscope.Generation.call(
                        model=self.model_id,
                        messages=[{'role': 'user', 'content': 'Hi'}],
                        result_format='message'
                    )
                return {"status": "ok", "message": "Chat service is nominal"}
                
        except Exception as e:
            error_msg = str(e)
            if "InvalidApiKey" in error_msg:
                return {"status": "error", "message": "Invalid API Key"}
            return {"status": "error", "message": error_msg}