# src/core/config_manager.py
"""
配置管理器
支持从数据库/环境变量读取配置，并提供统一的配置接口
"""
import os
import json
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, Text
from src.core.database import Base

logger = logging.getLogger(__name__)
from src.core.config_definitions import get_all_definitions, ConfigGroup




class SystemConfig(Base):
    """系统配置表"""
    __tablename__ = "system_config"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # [预留扩展] 多用户支持：用户 ID，默认值为 1（单用户模式）
    # TODO: 未来实现多用户时，此字段将从 Session/JWT 中获取
    user_id = Column(Integer, default=1, index=True, nullable=False, comment="用户ID，预留多用户扩展")
    
    config_key = Column(String(100), index=True, nullable=False)  # 移除 unique，改为与 user_id 联合唯一
    config_value = Column(Text, nullable=False)  # JSON 字符串
    description = Column(String(500), nullable=True)
    updated_at = Column(String(50), nullable=True)
    
    # TODO: 未来添加联合唯一索引: (user_id, config_key)


class ConfigManager:
    """配置管理器（单例模式）"""
    
    _instance = None
    _config_cache: Dict[str, Any] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._load_default_config()
    
    def _load_default_config(self):
        """加载默认配置（从环境变量）"""
        from src.core.config import settings
        
        self._config_cache = {
            "router": {
                "provider": os.getenv("ROUTER_PROVIDER", "gemini"),
                "model_id": os.getenv("ROUTER_MODEL", "gemini-2.5-flash"),
                "api_key": os.getenv("ROUTER_API_KEY", settings.GEMINI_API_KEY),
            },
            "reasoning": {
                "provider": os.getenv("REASONING_PROVIDER", "gemini"),
                "model_id": os.getenv("REASONING_MODEL", "gemini-2.5-flash"),
                "api_key": os.getenv("REASONING_API_KEY", settings.GEMINI_API_KEY),
            },
            "retrieval": {
                "vector_service_type": os.getenv("VECTOR_SERVICE_TYPE", "remote"),
                "remote_url": os.getenv("REMOTE_VECTOR_URL", ""),
                "remote_api_key": os.getenv("REMOTE_VECTOR_API_KEY", ""),
            },
            "audio": {
                "tts_provider": os.getenv("TTS_PROVIDER", "dashscope"),
                "tts_model": os.getenv("TTS_MODEL", "sambert-zhichu-v1"),
                "tts_api_key": os.getenv("TTS_API_KEY", settings.DASHSCOPE_API_KEY or settings.GEMINI_API_KEY),
            }
        }
        
        # Load defaults from schema definitions
        definitions = get_all_definitions()
        for group in definitions:
            for field in group.fields:
                # Key format: "group.key"
                if "." in field.key:
                    section, subkey = field.key.split(".", 1)
                    if section not in self._config_cache:
                        self._config_cache[section] = {}
                    
                    # Only set default if not already present (env vars take precedence if we mapped them above, 
                    # but new schema keys won't be in env vars usually)
                    if subkey not in self._config_cache[section]:
                        self._config_cache[section][subkey] = field.default

        # Special Handling: Sync environment variables for specific legacy keys if needed
        # (Already handled by the hardcoded block above for backward compatibility)
        
        logger.info("✅ config_manager initialized with schema validation.")
        logger.info("✅ 配置管理器初始化完成（使用默认配置）")
    
    def get_config(self, key: str, db: Optional[Session] = None, user_id: int = 1) -> Dict[str, Any]:
        """
        获取配置
        :param key: 配置键 (router/reasoning/retrieval)
        :param db: 数据库会话（可选）
        :param user_id: 用户ID，默认1（单用户模式），预留多用户扩展
        :return: 配置字典
        """
        # [预留扩展] 当前单用户模式，user_id 固定为 1
        # TODO: 未来多用户时，user_id 将从 Session/JWT 中获取
        
        if db:
            try:
                config_record = db.query(SystemConfig).filter(
                    SystemConfig.config_key == key,
                    SystemConfig.user_id == user_id  # [预留扩展] 按用户过滤
                ).first()
                
                if config_record:
                    config_value = json.loads(config_record.config_value)
                    self._config_cache[key] = config_value
                    return config_value
            except Exception as e:
                logger.warning(f"从数据库读取配置失败，使用缓存: {e}")
        
        return self._config_cache.get(key, {})
    
    def update_config(
        self,
        key: str,
        value: Dict[str, Any],
        db: Optional[Session] = None,
        description: Optional[str] = None,
        user_id: int = 1  # [预留扩展] 默认1，单用户模式
    ) -> bool:
        """
        更新配置
        :param key: 配置键
        :param value: 配置值（字典）
        :param db: 数据库会话
        :param description: 配置描述
        :param user_id: 用户ID，默认1（单用户模式），预留多用户扩展
        :return: 是否成功
        """
        # [预留扩展] 当前单用户模式，user_id 固定为 1
        # TODO: 未来多用户时，user_id 将从 Session/JWT 中获取
        
        try:
            self._config_cache[key] = value
            
            if db:
                from datetime import datetime
                
                config_record = db.query(SystemConfig).filter(
                    SystemConfig.config_key == key,
                    SystemConfig.user_id == user_id  # [预留扩展] 按用户过滤
                ).first()
                
                if config_record:
                    config_record.config_value = json.dumps(value, ensure_ascii=False)
                    config_record.updated_at = datetime.now().isoformat()
                    if description:
                        config_record.description = description
                else:
                    config_record = SystemConfig(
                        user_id=user_id,  # [预留扩展] 设置用户ID
                        config_key=key,
                        config_value=json.dumps(value, ensure_ascii=False),
                        description=description or "",
                        updated_at=datetime.now().isoformat()
                    )
                    db.add(config_record)
                
                db.commit()
                logger.info(f"✅ 配置已更新并持久化: {key} (user_id: {user_id})")
            
            return True
        except Exception as e:
            logger.error(f"❌ 更新配置失败: {e}")
            if db:
                db.rollback()
            return False
    
    def get_all_config(self, db: Optional[Session] = None, user_id: int = 1) -> Dict[str, Any]:
        """获取所有配置"""
        if db:
            try:
                configs = db.query(SystemConfig).filter(
                    SystemConfig.user_id == user_id  # [预留扩展] 按用户过滤
                ).all()
                result = {}
                for cfg in configs:
                    result[cfg.config_key] = json.loads(cfg.config_value)
                # 合并默认配置（数据库没有的键）
                for key in self._config_cache:
                    if key not in result:
                        result[key] = self._config_cache[key]
                
                # Apply defaults from schema for any missing nested keys within existing sections
                definitions = get_all_definitions()
                for group in definitions:
                    for field in group.fields:
                        if "." in field.key:
                            section, subkey = field.key.split(".", 1)
                            if section in result:
                                if subkey not in result[section]:
                                    result[section][subkey] = field.default
                            else:
                                result[section] = {subkey: field.default}

                return result
            except Exception as e:
                logger.warning(f"从数据库读取全部配置失败，使用缓存: {e}")
        
        return self._config_cache.copy()


    # [New] Initialize Defaults (Seeding)
    def initialize_defaults(self, db: Session, user_id: int = 1):
        """
        初始化默认配置到数据库 (Seeding)
        仅当数据库中没有配置时执行
        """
        try:
            # Check if any config exists for this user
            existing_count = db.query(SystemConfig).filter(SystemConfig.user_id == user_id).count()
            
            if existing_count == 0:
                logger.info("⚙️ 数据库配置为空，开始初始化默认配置 (Seeding)...")
                # Iterate over current cache (which holds env vars / defaults) and write to DB
                
                # Snapshot current cache to avoid iteration issues if it changes (unlikely here)
                defaults_to_seed = self._config_cache.copy()
                
                for key, value in defaults_to_seed.items():
                    # Create record
                    config_record = SystemConfig(
                        user_id=user_id,
                        config_key=key,
                        config_value=json.dumps(value, ensure_ascii=False),
                        description="Initialized from environment/defaults",
                        updated_at=None # Initial seed
                    )
                    db.add(config_record)
                
                db.commit()
                logger.info(f"✅ 已初始化 {len(defaults_to_seed)} 条默认配置到数据库。")
            else:
                logger.info("✅ 数据库已有配置，跳过初始化 (Using Immutable Configuration).")
                
                # [Critical] If DB exists, we MUST update our local cache to match DB immediately
                # because _load_default_config() loaded Env Vars, which might be stale/ignored now.
                self.get_all_config(db, user_id=user_id)
                
        except Exception as e:
            logger.error(f"❌ 初始化默认配置失败: {e}")
            db.rollback()

# 全局单例实例
config_manager = ConfigManager()