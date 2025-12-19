import logging
import asyncio
from typing import AsyncGenerator
try:
    import dashscope
    from dashscope.audio.tts import SpeechSynthesizer as LegacySpeechSynthesizer
    try:
        from dashscope.audio.qwen_tts import SpeechSynthesizer as QwenSpeechSynthesizer
    except ImportError:
        QwenSpeechSynthesizer = None
except ImportError:
    dashscope = None
    LegacySpeechSynthesizer = None
    QwenSpeechSynthesizer = None

from src.core.plugins import BasePlugin
from src.core.events import EventBus
from src.core.config import settings

logger = logging.getLogger(__name__)

class AudioIOPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "AudioIOPlugin"

    def register(self, bus: EventBus):
        pass
        
    async def synthesize(self, text: str) -> AsyncGenerator[bytes, None]:
        """Synthesize text to speech stream with model failover."""
        if not text:
            return

        if not dashscope:
            logger.error("Dashscope not installed")
            return

        from src.core.database import SessionLocal
        from src.core.model_manager import model_manager

        db = SessionLocal()
        try:
            # 1. 获取所有激活的语音模型 (已按优先级排序)
            voice_models = model_manager.get_active_models(db, agent_type="voice")
            
            # 如果没有配置模型，尝试向后兼容 (Fallback Legacy Config)
            if not voice_models:
                from src.core.config_manager import config_manager
                audio_config = config_manager.get_config("audio")
                if audio_config.get("tts_model"):
                    # 构造一个临时模型对象
                    from src.models.ai_config import AIModel
                    legacy_model = AIModel(
                        provider=audio_config.get("tts_provider", "dashscope"),
                        model_id=audio_config.get("tts_model"),
                        api_key=audio_config.get("tts_api_key"),
                        is_active=True,
                        name="Legacy Config Model",
                        config={}
                    )
                    voice_models = [legacy_model]

            if not voice_models:
                logger.error("No active voice models configured.")
                return

            logger.info(f"Found {len(voice_models)} active voice models. Starting synthesis...")

            # 2. Failover Loop
            last_error = None
            for idx, model in enumerate(voice_models):
                try:
                    # 配置 API Key
                    dashscope.api_key = model.api_key or settings.DASHSCOPE_API_KEY
                    
                    model_id_lower = model.model_id.lower()
                    is_qwen = "qwen" in model_id_lower or "cosy" in model_id_lower
                    
                    logger.info(f"TTS Attempt {idx+1}/{len(voice_models)}: using model {model.name} ({model.model_id})")
                    
                    # 提取参数 (voice, format, volume, etc.)
                    # model.config 是 JSON 字段
                    model_config = model.config or {}
                    voice = model_config.get("voice", "longxiaochun") # Default for legacy
                    if is_qwen:
                         # Qwen-TTS 默认 voice 通常是 Cherry 等，但也支持传入
                         voice = model_config.get("voice", "Cherry")
                    
                    result = None
                    if is_qwen:
                        if not QwenSpeechSynthesizer:
                            raise ImportError("dashscope SDK version too old, qwen_tts not available. Please upgrade dashscope>=1.23.1")
                        
                        logger.info(f"   -> Using Qwen-TTS SDK (Voice: {voice})")
                        result = QwenSpeechSynthesizer.call(
                            model=model.model_id,
                            text=text,
                            voice=voice,
                            # Qwen-TTS 不一定支持 format/sample_rate 所有参数，视具体模型而定，这里保持简约
                        )
                    else:
                        logger.info(f"   -> Using Legacy/Sambert SDK (Voice: {voice})")
                        result = LegacySpeechSynthesizer.call(
                            model=model.model_id, 
                            text=text, 
                            sample_rate=48000, 
                            format='mp3',
                            voice=voice
                        )
                    
                    audio_data = None
                    # 统一检查 HTTP Status (DashScope SDK returns .status_code)
                    status_code = getattr(result, 'status_code', 200)
                    if status_code == 200:
                        if is_qwen:
                            # Qwen-TTS Response Handling
                            if hasattr(result, 'output'):
                                output = result.output
                                logger.info(f"Qwen TTS Output Type: {type(output)}")
                                
                                if isinstance(output, (bytes, bytearray)):
                                    audio_data = output
                                else:
                                    # Try to find 'audio' field
                                    candidate = None
                                    if isinstance(output, dict):
                                        candidate = output.get('audio')
                                    elif hasattr(output, 'audio'):
                                        candidate = output.audio
                                    
                                    # Also check 'choices' for text-like response
                                    if candidate is None and (hasattr(output, 'choices') and output.choices):
                                        try:
                                            candidate = output.choices[0].message.content
                                        except:
                                            pass
                                    
                                    # Validate candidate
                                    if isinstance(candidate, (bytes, bytearray)):
                                        audio_data = candidate
                                    elif candidate is not None:
                                        if isinstance(candidate, str) and candidate.startswith("http"):
                                             # Direct URL string
                                             try:
                                                 import requests
                                                 logger.info(f"Downloading Audio from URL: {candidate}")
                                                 resp = requests.get(candidate, timeout=30)
                                                 resp.raise_for_status()
                                                 audio_data = resp.content
                                             except Exception as dl_err:
                                                 logger.error(f"Failed to download audio from URL: {dl_err}")
                                        
                                        elif isinstance(candidate, dict) and "url" in candidate:
                                             # Dict with URL (e.g. {'url': '...', ...})
                                             url = candidate["url"]
                                             try:
                                                 import requests
                                                 logger.info(f"Downloading Audio from dictionary URL: {url}")
                                                 resp = requests.get(url, timeout=30)
                                                 resp.raise_for_status()
                                                 audio_data = resp.content
                                             except Exception as dl_err:
                                                 logger.error(f"Failed to download audio from dict URL: {dl_err}")
                                        else:
                                            logger.warning(f"Qwen TTS 'audio' field unhandled type: {type(candidate)} - {candidate}")

                            # Fallback: check if get_audio_data exists
                            # Note: DashScope SDK might raise KeyError if we access a non-existent attr via __getattr__ logic
                            if audio_data is None:
                                try:
                                    # Safely check for get_audio_data method without triggering __getattr__ KeyError if possible
                                    # But hasattr triggers __getattr__.
                                    # We just wrap in try-except
                                    if hasattr(result, 'get_audio_data'):
                                        audio_data = result.get_audio_data()
                                except (KeyError, AttributeError):
                                    # Ignore SDK specific errors when accessing legacy method on new response
                                    pass
                        else:
                            # Legacy Sambert Response Handling
                            if hasattr(result, 'get_audio_data'):
                                audio_data = result.get_audio_data()

                    if audio_data is not None:
                        if not isinstance(audio_data, (bytes, bytearray)):
                            logger.error(f"FATAL: audio_data is {type(audio_data)}, expected bytes! Dropping.")
                            audio_data = None # Prevent crash in yield
                        else:
                             # logger.info(f"TTS Success: {model.name} (Bytes: {len(audio_data)})") 
                             # (Reduce noise, success logged above if needed, or we log here)
                             logger.info(f"TTS Success: {model.name} (Bytes: {len(audio_data)})")
                             
                             chunk_size = 1024 * 16 # 16KB chunks
                             for i in range(0, len(audio_data), chunk_size):
                                 yield audio_data[i:i+chunk_size]
                                 await asyncio.sleep(0) # Yield control
                             return # Success! Exit loop.
                    else:
                        code = getattr(result, 'code', 'Unknown')
                        msg = getattr(result, 'message', 'Unknown error')
                        if hasattr(result, 'output'):
                             # Log output structure for debugging if failed
                             logger.debug(f"Failed TTS Response Output: {result.output}")
                        
                        logger.warning(f"TTS Model {model.name} Failed (Status {status_code}): {code} - {msg}")
                        last_error = f"{code} - {msg}"
                        if idx < len(voice_models) - 1:
                            logger.info("Switching to next model...")
                        continue # Try next model
                        
                except Exception as e:
                    logger.warning(f"TTS Model {model.name} Error: {e}", exc_info=True)
                    last_error = str(e)
                    if idx < len(voice_models) - 1:
                        logger.info("Switching to next model...")
                    continue

            # All attempts failed
            logger.error(f"All TTS models failed. Last error: {last_error}")

        finally:
            db.close()
