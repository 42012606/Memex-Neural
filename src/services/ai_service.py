"""
AI 服务统一入口
支持模型池 (reasoning/router) + 自动故障切换，兼容旧配置。
"""
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from starlette.concurrency import run_in_threadpool

from src.core.config_manager import config_manager
from src.core.database import SessionLocal
from src.core.model_manager import model_manager
from src.core.config import settings
from src.services.ai.factory import AIProviderFactory
from src.core.prompt_manager import prompt_manager # [New]

logger = logging.getLogger(__name__)


class AIService:
    def __init__(self, service_type: str = "reasoning"):
        # service_type: reasoning / router
        self.service_type = service_type
        self._provider = None  # legacy 单模型
        self._pool_providers = []  # [{"priority": int, "db_id": int, "name": str, "instance": provider}]
        self._allow_failover = self.service_type == "router"  # 路由允许自动切换，推理仅报错
        self._user_profile_cache: Optional[str] = None

    # --- Provider builders ---
    def _get_agent_type(self) -> str:
        return "router" if self.service_type == "router" else "reasoning"

    def _build_provider(self, model, db) -> Any:
        api_key = model.api_key
        if not api_key:
            legacy_cfg = config_manager.get_config(self.service_type, db=db)
            if legacy_cfg.get("provider") == model.provider:
                api_key = legacy_cfg.get("api_key")
        
        # ✅ 新增: 读取预设配置
        extra_config = model.config or {}
        
        return AIProviderFactory.create(
            provider_type=model.provider,
            api_key=api_key or "",
            model_id=model.model_id,
            base_url=model.base_url,
            extra_config=extra_config,  # ✅ 传递额外配置
        )

    def _load_pool(self, db_session=None):
        db = db_session or SessionLocal()
        try:
            active_models = model_manager.get_active_models(db, agent_type=self._get_agent_type())
            providers = []
            for m in active_models:
                try:
                    providers.append(
                        {
                            "priority": m.priority,
                            "db_id": m.id,
                            "name": m.name,
                            "instance": self._build_provider(m, db),
                        }
                    )
                except Exception as e:
                    logger.error(f"❌ 加载模型池项 {m.name} 失败: {e}")
            providers.sort(key=lambda x: (x["priority"],))
            self._pool_providers = providers
            if providers:
                logger.info(f"✅ {self._get_agent_type()} 模型池加载完成，共 {len(providers)} 个")
        except Exception as e:
            logger.error(f"加载模型池失败: {e}")
        finally:
            if not db_session:
                db.close()

    def _load_legacy_provider(self, db=None):
        config = config_manager.get_config(self.service_type, db=db)
        provider_type = config.get("provider", "gemini")
        api_key = config.get("api_key", "")
        model_id = config.get("model_id")
        if not api_key:
            raise ValueError(f"{self.service_type} 服务的 API Key 未配置")
        self._provider = AIProviderFactory.create(
            provider_type=provider_type,
            api_key=api_key,
            model_id=model_id,
            base_url=config.get("base_url"),
        )

    def _get_user_profile_text(self) -> str:
        """读取用户画像，头部注入到 System Prompt"""
        if self._user_profile_cache is not None:
            return self._user_profile_cache
        profile_path = Path(settings.DATA_DIR) / "user_profile.md"
        try:
            text = profile_path.read_text(encoding="utf-8")
            self._user_profile_cache = text.strip()
        except Exception as e:
            logger.warning(f"读取 user_profile.md 失败: {e}")
            self._user_profile_cache = ""
        return self._user_profile_cache or ""

    # --- Core chat with failover ---
    async def chat(
        self,
        query: str,
        context: str = "",
        model_id: Optional[str] = None,
        intent: Optional[str] = None,
        file_ids: Optional[list] = None,
        system_prompt: Optional[str] = None,
        db_session=None,
    ) -> Dict[str, str]:
        from src.core.error_translator import translate_ai_error
        
        db = db_session or SessionLocal()
        try:
            profile = self._get_user_profile_text()
            # --- retry helper ---
            async def _call_with_retry(callable_fn, *, model_name: str) -> Any:
                import asyncio

                max_retries = 2
                last_error = None
                for attempt in range(max_retries):
                    try:
                        return await run_in_threadpool(callable_fn)
                    except Exception as e:
                        last_error = e
                        err_str = str(e).lower()
                        logger.warning(f"⚠️ AI Call Failed (Attempt {attempt+1}/{max_retries}) on {model_name}: {e}")
                        if ("api key" in err_str) or ("invalid" in err_str) or ("频率" in err_str) or ("配额" in err_str) or ("quota" in err_str) or ("rate" in err_str):
                            raise e
                        await asyncio.sleep(1 * (attempt + 2))  # 拉长退避：2s,3s
                logger.error(f"❌ AI Service Exhausted all {max_retries} retries for {model_name}. Last error: {last_error}")
                raise last_error
            
            # 构建系统提示（遵循单一系统消息原则）
            if system_prompt:
                # 如果提供了自定义系统提示，合并 User Profile
                if profile:
                    final_system_prompt = f"{system_prompt}\n\n[User Profile]\n{profile}"
                else:
                    final_system_prompt = system_prompt
            else:
                # 如果没有提供系统提示，使用默认并添加 User Profile
                default_system = prompt_manager.get("system.chat_default", default="你是一个智能助手 Memex。请尽力回答用户的问题。如果提供了上下文信息，请优先基于上下文回答，并引用来源。")
                if profile:
                    final_system_prompt = f"{default_system}\n\n[User Profile]\n{profile}"
                else:
                    final_system_prompt = default_system
            
            composed_context = context or ""

            # 若为精读/分析场景，强制注入全文内容
            if intent == "analyze" and file_ids:
                try:
                    from src.models.archive import ArchiveRecord

                    q = db.query(ArchiveRecord).filter(ArchiveRecord.id.in_(file_ids))
                    docs = q.all()
                    full_blocks = []
                    for doc in docs:
                        if getattr(doc, "full_text", None):
                            full_blocks.append(
                                f"Here is the FULL CONTENT of the file {doc.filename}:\n---\n{doc.full_text}\n---\n"
                            )
                    if full_blocks:
                        composed_context = (composed_context + "\n\n" + "\n".join(full_blocks)).strip()
                except Exception as e:
                    logger.warning(f"注入全文失败: {e}")

            # 1) 用户指定模型模式（Reasoning/User 模式：禁止 Failover，立即报错）
            if model_id:
                try:
                    model = self._fetch_model(db, model_id)
                    provider = self._build_provider(model, db)
                    # --- DIAGNOSTIC LOGGING START ---
                    try:
                        prompt_len = len(str(query)) if query else 0
                        sys_len = len(str(final_system_prompt)) if final_system_prompt else 0
                        total_est = prompt_len + sys_len
                        logger.info(
                            f"🔍 AI PAYLOAD CHECK: Model={model.model_id} | Type={self.service_type} | "
                            f"PromptLen={prompt_len} | SystemLen={sys_len} | TotalChars={total_est}"
                        )
                        if total_est > 10000:
                            logger.warning("⚠️ MASSIVE PAYLOAD DETECTED (>10k chars)! This may cause timeouts.")
                    except Exception as diag_e:
                        logger.error(f"Diagnostic log failed: {diag_e}")
                    # --- DIAGNOSTIC LOGGING END ---
                    reply = await _call_with_retry(
                        lambda: provider.chat(query, composed_context, system_prompt=final_system_prompt),
                        model_name=model.name,
                    )
                    if self._is_error_reply(reply):
                        # 用户指定模型失败，立即抛出错误（禁止 Failover）
                        error_msg = translate_ai_error(reply)
                        logger.warning(f"⚠️ 用户指定模型 {model.name} 失败: {error_msg}")
                        raise Exception(f"指定模型失败: {error_msg}")
                    return {"reply": reply, "model_id": str(model.id)}
                except Exception as e:
                    # 用户指定模型失败，立即抛出错误（禁止 Failover）
                    error_msg = translate_ai_error(str(e))
                    logger.warning(f"⚠️ 用户指定模型调用失败: {error_msg}")
                    raise Exception(f"指定模型失败: {error_msg}")

            # 2) 池模式 + 故障切换
            if not self._pool_providers:
                self._load_pool(db_session=db)

            if self._pool_providers:
                # 2A) Router/Auto 模式（高可用：必须实现死循环 Failover）
                if self._allow_failover or self.service_type == "router":
                    errors = []
                    for item in self._pool_providers:
                        try:
                            # --- DIAGNOSTIC LOGGING START ---
                            try:
                                prompt_len = len(str(query)) if query else 0
                                sys_len = len(str(final_system_prompt)) if final_system_prompt else 0
                                total_est = prompt_len + sys_len
                                logger.info(
                                    f"🔍 AI PAYLOAD CHECK: Model={item['name']} | Type={self.service_type} | "
                                    f"PromptLen={prompt_len} | SystemLen={sys_len} | TotalChars={total_est}"
                                )
                                if total_est > 10000:
                                    logger.warning("⚠️ MASSIVE PAYLOAD DETECTED (>10k chars)! This may cause timeouts.")
                            except Exception as diag_e:
                                logger.error(f"Diagnostic log failed: {diag_e}")
                            # --- DIAGNOSTIC LOGGING END ---
                            reply = await _call_with_retry(
                                lambda: item["instance"].chat(query, composed_context, system_prompt=final_system_prompt),
                                model_name=item["name"],
                            )
                            if self._is_error_reply(reply):
                                # 返回错误字符串，记录并继续尝试下一个（死循环 Failover）
                                error_msg = translate_ai_error(reply)
                                logger.warning(f"⚠️ Router模型 {item['name']} 返回错误，切换到下一个模型: {error_msg}")
                                errors.append(f"{item['name']}: {error_msg}")
                                continue
                            # 成功，返回结果
                            logger.info(f"✅ Router模型 {item['name']} 调用成功")
                            return {"reply": reply, "model_id": str(item["db_id"])}
                        except Exception as e:
                            # Provider 抛出异常，记录并继续尝试下一个（死循环 Failover）
                            error_msg = translate_ai_error(str(e))
                            logger.warning(f"⚠️ Router模型 {item['name']} 调用失败，切换到下一个模型: {error_msg}")
                            errors.append(f"{item['name']}: {error_msg}")
                            continue
                    # 所有模型都失败，才抛出异常
                    all_errors = "; ".join(errors) if errors else "未知错误"
                    raise Exception(f"所有Router模型失败: {all_errors}")
                
                # 2B) Reasoning/User 模式（强一致：禁止 Failover，仅尝试首选）
                else:
                    item = self._pool_providers[0]
                    try:
                        reply = await _call_with_retry(
                            lambda: item["instance"].chat(query, composed_context, system_prompt=final_system_prompt),
                            model_name=item["name"],
                        )
                        if self._is_error_reply(reply):
                            error_msg = translate_ai_error(reply)
                            logger.error(f"❌ 推理模型 {item['name']} 返回错误: {error_msg}")
                            raise Exception(f"推理模型失败: {error_msg}")
                        return {"reply": reply, "model_id": str(item["db_id"])}
                    except Exception as e:
                        error_msg = translate_ai_error(str(e))
                        logger.error(f"❌ 推理模型 {item['name']} 调用失败: {error_msg}")
                        raise Exception(f"推理模型失败: {error_msg}")

            # 3) Legacy fallback
            try:
                logger.info("ℹ️ 模型池为空，使用 Legacy 配置")
                reply = await self._chat_legacy(query, composed_context, system_prompt=final_system_prompt)
                if self._is_error_reply(reply):
                    error_msg = translate_ai_error(reply)
                    raise Exception(f"Legacy 配置返回错误: {error_msg}")
                return {"reply": reply, "model_id": "legacy"}
            except Exception as e:
                error_msg = translate_ai_error(str(e))
                logger.error(f"❌ Legacy 配置也失败: {error_msg}")
                raise Exception(f"所有配置路径失败: {error_msg}")
        finally:
            if not db_session:
                db.close()

    def _fetch_model(self, db, model_id: str):
        try:
            db_id = int(model_id)
        except (TypeError, ValueError):
            raise ValueError("model_id 必须是有效的模型记录 ID")
        model = model_manager.get_model(db, db_id)
        if not model or not model.is_active:
            raise ValueError("指定的模型不可用")
        expected_type = self._get_agent_type()
        if model.agent_type != expected_type:
            raise ValueError(f"模型类型不匹配，期望 {expected_type}")
        return model

    async def _chat_legacy(self, query: str, context: str, system_prompt: str = None) -> str:
        if not self._provider:
            self._load_legacy_provider()
        return await run_in_threadpool(self._provider.chat, query, context, system_prompt=system_prompt)

    # --- Sync generation ---
    def generate_text(self, prompt: str, model_id: Optional[str] = None) -> str:
        from src.core.error_translator import translate_ai_error
        
        db = SessionLocal()
        try:
            if model_id:
                try:
                    model = self._fetch_model(db, model_id)
                    provider = self._build_provider(model, db)
                    result = provider.generate_text(prompt)
                    if self._is_error_reply(result):
                        error_msg = translate_ai_error(result)
                        logger.warning(f"⚠️ 指定模型生成失败: {error_msg}")
                        raise Exception(error_msg)
                    return result
                except Exception as e:
                    error_msg = translate_ai_error(str(e))
                    logger.warning(f"⚠️ 指定模型调用失败: {error_msg}")
                    raise Exception(error_msg)

            if not self._pool_providers:
                self._load_pool(db_session=db)
            if self._pool_providers:
                errors = []
                for item in self._pool_providers:
                    try:
                        result = item["instance"].generate_text(prompt)
                        if self._is_error_reply(result):
                            error_msg = translate_ai_error(result)
                            logger.warning(f"⚠️ 模型 {item['name']} 生成失败: {error_msg}")
                            errors.append(f"{item['name']}: {error_msg}")
                            continue
                        return result
                    except Exception as e:
                        error_msg = translate_ai_error(str(e))
                        logger.warning(f"⚠️ 模型 {item['name']} 调用失败: {error_msg}")
                        errors.append(f"{item['name']}: {error_msg}")
                        continue
                all_errors = "; ".join(errors) if errors else "未知错误"
                raise Exception(f"所有模型池失败: {all_errors}")

            if not self._provider:
                self._load_legacy_provider(db=db)
            result = self._provider.generate_text(prompt)
            if self._is_error_reply(result):
                error_msg = translate_ai_error(result)
                raise Exception(f"Legacy 配置失败: {error_msg}")
            return result
        finally:
            db.close()

    # --- File analysis with failover ---
    def analyze_file(self, file_path: Path, model_id: Optional[str] = None, context_text: Optional[str] = None, db_session=None) -> dict:
        """
        分析文件，支持模型池 Failover
        :param file_path: 文件路径
        :param model_id: 指定模型 ID（可选）
        :param context_text: 上下文文本（OCR/转录结果）
        :param db_session: 数据库会话（可选）
        :return: 分析结果字典
        """
        from src.core.error_translator import translate_ai_error
        
        db = db_session or SessionLocal()
        errors = []
        
        try:
            # 1) 用户指定模型模式（Reasoning/User 模式：禁止 Failover，立即报错）
            if model_id:
                try:
                    model = self._fetch_model(db, model_id)
                    provider = self._build_provider(model, db)
                    result = provider.analyze_file(file_path, context_text=context_text)
                    if result and not result.get("semantic", {}).get("error"):
                        return result
                    # 用户指定模型失败，立即抛出错误（禁止 Failover）
                    error_info = result.get("semantic", {}).get("error", "Unknown error") if result else "Analysis failed"
                    error_msg = translate_ai_error(error_info)
                    logger.error(f"❌ 用户指定模型 {model.name} 分析失败: {error_msg}")
                    raise Exception(f"指定模型分析失败: {error_msg}")
                except Exception as e:
                    error_msg = translate_ai_error(str(e))
                    logger.error(f"❌ 用户指定模型调用失败: {error_msg}")
                    raise Exception(f"指定模型失败: {error_msg}")
            
            # 2) 模型池模式 + Failover（仅 reasoning 类型）
            if not self._pool_providers:
                self._load_pool(db_session=db)
            
            if self._pool_providers:
                # 2A) Router/Auto 模式（高可用：必须实现死循环 Failover）
                # analyze_file 通常用于文件分析，默认使用 reasoning 类型，但支持 Failover
                errors = []
                for item in self._pool_providers:
                    try:
                        result = item["instance"].analyze_file(file_path, context_text=context_text)
                        if result and not result.get("semantic", {}).get("error"):
                            logger.info(f"✅ 模型 {item['name']} 分析成功")
                            return result
                        # 如果返回了错误，记录并尝试下一个（死循环 Failover）
                        error_info = result.get("semantic", {}).get("error", "Unknown error") if result else "Analysis failed"
                        error_msg = translate_ai_error(error_info)
                        errors.append(f"{item['name']}: {error_msg}")
                        logger.warning(f"⚠️ 模型 {item['name']} 分析失败，切换到下一个模型: {error_msg}")
                        continue
                    except Exception as e:
                        error_msg = translate_ai_error(str(e))
                        errors.append(f"{item['name']}: {error_msg}")
                        logger.warning(f"⚠️ 模型 {item['name']} 调用失败，切换到下一个模型: {error_msg}")
                        continue
                
                # 所有模型池都失败
                all_errors = "; ".join(errors) if errors else "未知错误"
                logger.error(f"❌ 所有模型池分析失败: {all_errors}")
                raise Exception(f"所有模型分析失败: {all_errors}")
            
            # 3) Legacy fallback
            if not self._provider:
                self._load_legacy_provider(db=db)
            
            try:
                result = self._provider.analyze_file(file_path, context_text=context_text)
                if result and not result.get("semantic", {}).get("error"):
                    return result
                error_info = result.get("semantic", {}).get("error", "Unknown error") if result else "Analysis failed"
                error_msg = translate_ai_error(error_info)
                errors.append(f"Legacy: {error_msg}")
                logger.warning(f"⚠️ Legacy 模型分析失败: {error_msg}")
            except Exception as e:
                error_msg = translate_ai_error(str(e))
                errors.append(f"Legacy: {error_msg}")
                logger.error(f"❌ Legacy 模型调用失败: {error_msg}")
            
            # 所有路径都失败
            all_errors = "; ".join(errors) if errors else "未知错误"
            raise Exception(f"所有分析路径失败: {all_errors}")
            
        finally:
            if not db_session:
                db.close()

    # --- Helper to detect textual error and trigger failover ---
    def _is_error_reply(self, reply: Optional[str]) -> bool:
        """检测回复是否为错误信息"""
        if not isinstance(reply, str):
            return False
        lowered = reply.lower()
        error_keywords = [
            "error",
            "failed",
            "失败",
            "短路",
            "发生错误",
            "api key",
            "api_key",
            "invalid",
            "unauthorized",
            "forbidden",
            "400 ",
            "401 ",
            "403 ",
            "404 ",
            "500 ",
            "502 ",
            "503 ",
            "504 ",
            "quota",
            "limit",
            "timeout",
            "connection",
        ]
        return any(k in lowered for k in error_keywords)
    
    # --- Vision/Audio/Embedding Services ---
    
    def recognize_image(self, image_url: str, db_session=None) -> str:
        """
        图片OCR识别
        :param image_url: 图片URL或本地文件路径
        :param db_session: 数据库会话（可选）
        :return: 提取的文本内容
        """
        db = db_session or SessionLocal()
        try:
            # 获取Vision模型
            vision_models = model_manager.get_active_models(db, agent_type="vision")
            if not vision_models:
                raise ValueError("未配置视觉模型，请在配置页面添加 Vision 模型")
            
            logger.info(f"Using Vision Models: {[m.name for m in vision_models]}")
            
            last_error = None
            for idx, model in enumerate(vision_models):
                try:
                    provider = self._build_provider(model, db)
                    # 调用DashScope Vision API
                    if hasattr(provider, 'recognize_image'):
                        result = provider.recognize_image(image_url)
                        logger.info(f"✅ 图片通过模型 {model.name} 识别成功")
                        return result
                    else:
                        raise ValueError(f"Provider {model.provider} 不支持图片识别")
                except Exception as e:
                    error_msg = str(e)
                    logger.warning(f"⚠️ 图片识别模型 {model.name} 失败: {error_msg}")
                    last_error = error_msg
                    if idx < len(vision_models) - 1:
                        logger.info("Switching to next model...")
                    continue
            
            raise Exception(f"所有视觉模型均失败。Last Error: {last_error}")

        finally:
            if not db_session:
                db.close()
    
    def transcribe_audio(self, file_path: Path, db_session=None) -> str:
        """
        音频转录
        :param file_path: 音频文件路径
        :param db_session: 数据库会话（可选）
        :return: 转录的文本内容
        """
        db = db_session or SessionLocal()
        try:
            # 获取Audio模型
            audio_models = model_manager.get_active_models(db, agent_type="audio")
            if not audio_models:
                raise ValueError("未配置听觉模型，请在配置页面添加 Audio 模型")
            
            logger.info(f"Using Hearing Models (STT): {[m.name for m in audio_models]}")
            
            last_error = None
            for idx, model in enumerate(audio_models):
                try:
                    provider = self._build_provider(model, db)
                    if hasattr(provider, 'transcribe_audio'):
                        logger.info(f"👂 Attempting transcription with {model.name}...")
                        result = provider.transcribe_audio(file_path)
                        logger.info(f"✅ 音频通过模型 {model.name} 转录成功")
                        return result
                    else:
                        raise ValueError(f"Provider {model.provider} 不支持音频转录")
                except Exception as e:
                    error_msg = str(e)
                    logger.warning(f"⚠️ 听觉模型 {model.name} 转录失败: {error_msg}")
                    last_error = error_msg
                    if idx < len(audio_models) - 1:
                        logger.info("Switching to next model...")
                    continue
            
            raise Exception(f"所有听觉模型(STT)均失败。Last Error: {last_error}")

        finally:
            if not db_session:
                db.close()
    
    def synthesize_audio(self, text: str, db_session=None) -> bytes:
        """
        语音合成 (TTS)
        :param text: 要合成的文本
        :param db_session: 数据库会话（可选）
        :return: 音频二进制数据
        """
        db = db_session or SessionLocal()
        try:
            # 获取Voice模型 (TTS)
            voice_models = model_manager.get_active_models(db, agent_type="voice")
            if not voice_models:
                raise ValueError("未配置语音模型，请在配置页面添加 Voice 模型")
            
            logger.info(f"Using Voice Models (TTS): {[m.name for m in voice_models]}")
            
            last_error = None
            for idx, model in enumerate(voice_models):
                try:
                    provider = self._build_provider(model, db)
                    if hasattr(provider, 'synthesize_audio'):
                        logger.info(f"🔊 Attempting TTS with {model.name}...")
                        result = provider.synthesize_audio(text)
                        logger.info(f"✅ 语音通过模型 {model.name} 合成成功")
                        return result
                    else:
                        raise ValueError(f"Provider {model.provider} 不支持语音合成")
                except Exception as e:
                    error_msg = str(e)
                    logger.warning(f"⚠️ 语音模型 {model.name} 合成失败: {error_msg}")
                    last_error = error_msg
                    if idx < len(voice_models) - 1:
                        logger.info("Switching to next model...")
                    continue
            
            raise Exception(f"所有语音模型(TTS)均失败。Last Error: {last_error}")

        finally:
            if not db_session:
                db.close()
    
    def embed_text(self, text: str, db_session=None) -> list:
        """
        文本向量化
        :param text: 输入文本
        :param db_session: 数据库会话（可选）
        :return: 向量列表
        """
        db = db_session or SessionLocal()
        try:
            # 获取Embedding模型
            embedding_models = model_manager.get_active_models(db, agent_type="embedding")
            if not embedding_models:
                raise ValueError("未配置记忆模型，请在配置页面添加 Embedding 模型")
            
            last_error = None
            for idx, model in enumerate(embedding_models):
                try:
                    provider = self._build_provider(model, db)
                    if hasattr(provider, 'embed_text'):
                        return provider.embed_text(text)
                    else:
                        raise ValueError(f"Provider {model.provider} 不支持文本向量化")
                except Exception as e:
                    logger.warning(f"⚠️ 记忆模型 {model.name} 向量化失败: {e}")
                    last_error = str(e)
                    continue

            raise Exception(f"所有记忆模型均失败。Last Error: {last_error}")
                
        finally:
            if not db_session:
                db.close()