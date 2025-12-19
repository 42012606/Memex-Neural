import logging
import json
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from src.models.ai_config import AIModel
from src.core.database import SessionLocal

logger = logging.getLogger(__name__)

class ModelManager:
    """
    AI 模型池管理器
    负责 AIModel 表的 CRUD 操作
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_active_models(self, db: Session, agent_type: Optional[str] = None) -> List[AIModel]:
        """获取激活的模型，按优先级 -> 创建时间排序"""
        try:
            query = db.query(AIModel).filter(AIModel.is_active == True)
            if agent_type:
                query = query.filter(AIModel.agent_type == agent_type)
            return query.order_by(AIModel.priority.asc(), AIModel.created_at.asc()).all()
        except Exception as e:
            logger.error(f"Failed to get active models: {e}")
            return []

    def get_all_models(self, db: Session, agent_type: Optional[str] = None) -> List[AIModel]:
        """获取所有模型，可选按 agent_type 过滤"""
        query = db.query(AIModel)
        if agent_type:
            query = query.filter(AIModel.agent_type == agent_type)
        return query.order_by(AIModel.priority.asc(), AIModel.created_at.asc()).all()
    
    def get_model(self, db: Session, model_id: int) -> Optional[AIModel]:
        """根据ID获取模型"""
        return db.query(AIModel).filter(AIModel.id == model_id).first()
    
    def get_router_config(self, db: Session) -> Optional[AIModel]:
        """获取Router Agent配置（应该只有1条）"""
        return db.query(AIModel).filter(
            AIModel.agent_type == 'router',
            AIModel.is_active == True
        ).first()
    
    def get_reasoning_models(self, db: Session) -> List[AIModel]:
        """获取所有推理模型，按优先级排序"""
        return self.get_all_models(db, agent_type='reasoning')
    
    def get_retrieval_config(self, db: Session) -> Optional[AIModel]:
        """获取Retrieval Agent配置（应该只有1条）"""
        return db.query(AIModel).filter(
            AIModel.agent_type == 'retrieval',
            AIModel.is_active == True
        ).first()

    def add_model(self, db: Session, model_data: Dict[str, Any]) -> AIModel:
        """添加新模型"""
        try:
            # 提取 known fields
            config_json = model_data.get("config", {})
            if isinstance(config_json, str):
                try:
                    config_json = json.loads(config_json)
                except:
                    config_json = {}
            
            agent_type = model_data.get("agent_type", "reasoning")
            
            # Retrieval 和 Embedding 只允许1条记录，检查是否已存在（Router/Reasoning/Vision/Audio 支持多个模型）
            if agent_type in ['retrieval', 'embedding']:
                existing = db.query(AIModel).filter(AIModel.agent_type == agent_type).first()
                if existing:
                    # 更新现有记录而不是创建新的
                    return self.update_model(db, existing.id, model_data)

            new_model = AIModel(
                agent_type=agent_type,
                name=model_data["name"],
                provider=model_data["provider"],
                model_id=model_data["model_id"],
                api_key=model_data.get("api_key"),
                base_url=model_data.get("base_url"),
                priority=model_data.get("priority", 0),
                is_active=model_data.get("is_active", True),
                config=config_json
            )
            db.add(new_model)
            db.commit()
            db.refresh(new_model)
            return new_model
        except Exception as e:
            db.rollback()
            logger.error(f"Add model failed: {e}")
            raise e

    def update_model(self, db: Session, db_id: int, update_data: Dict[str, Any]) -> Optional[AIModel]:
        """更新模型"""
        model = self.get_model(db, db_id)
        if not model:
            return None
        
        try:
            # 处理 config 字段
            if 'config' in update_data:
                config_json = update_data['config']
                if isinstance(config_json, str):
                    try:
                        config_json = json.loads(config_json)
                    except:
                        config_json = {}
                update_data['config'] = config_json
            
            for key, value in update_data.items():
                if hasattr(model, key) and key != 'id':  # 不允许更新ID
                    setattr(model, key, value)
            
            db.commit()
            db.refresh(model)
            return model
        except Exception as e:
            db.rollback()
            logger.error(f"Update model failed: {e}")
            raise e
    
    def reorder_models(self, db: Session, agent_type: str, model_priorities: List[Dict[str, int]]) -> bool:
        """批量更新模型优先级（用于拖动排序）
        model_priorities: [{"id": 1, "priority": 0}, {"id": 2, "priority": 1}, ...]
        """
        try:
            seen_ids = set()
            for item in model_priorities:
                model_id = item.get("id")
                priority = item.get("priority")
                if model_id is None or priority is None:
                    raise ValueError("id 和 priority 必须同时提供")

                if model_id in seen_ids:
                    raise ValueError(f"重复的模型ID: {model_id}")
                seen_ids.add(model_id)

                model = self.get_model(db, model_id)
                if not model:
                    raise ValueError(f"模型不存在: {model_id}")
                if model.agent_type != agent_type:
                    raise ValueError(f"模型 {model_id} 类型不匹配，期望 {agent_type}")

                model.priority = int(priority)
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Reorder models failed: {e}")
            raise e

    def delete_model(self, db: Session, db_id: int) -> bool:
        """删除模型"""
        model = self.get_model(db, db_id)
        if not model:
            return False
            
        try:
            db.delete(model)
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Delete model failed: {e}")
            raise e

    def initialize_defaults(self, db: Session):
        """
        初始化默认 AI 模型 (Seeding)
        """
        try:
            count = db.query(AIModel).count()
            if count == 0:
                logger.info("🤖 AI 模型列表为空，开始初始化默认模型...")
                from src.core.config import settings
                
                # Determine provider from Env or Default
                # We prioritize Gemini as per current settings
                
                defaults = [
                    # 1. Router
                    {
                        "agent_type": "router",
                        "name": "Router (Gemini)",
                        "provider": "gemini",
                        "model_id": "gemini-2.0-flash-exp", # Default as per previous knowledge or safe default
                        "priority": 0,
                        "api_key": settings.GEMINI_API_KEY
                    },
                    # 2. Reasoning
                    {
                        "agent_type": "reasoning",
                        "name": "Reasoning (Gemini)",
                        "provider": "gemini", 
                        "model_id": "gemini-2.0-flash-exp",
                        "priority": 0,
                        "api_key": settings.GEMINI_API_KEY
                    },
                    # 3. Vision
                    {
                        "agent_type": "vision",
                        "name": "Vision (Gemini)",
                        "provider": "gemini",
                        "model_id": "gemini-1.5-pro",
                        "priority": 0,
                        "api_key": settings.GEMINI_API_KEY
                    }
                ]
                
                for m_data in defaults:
                    self.add_model(db, m_data)
                
                logger.info(f"✅ 已初始化 {len(defaults)} 个默认 AI 模型。")
            else:
                logger.info("✅ 数据库已有模型配置，跳过初始化。")
        except Exception as e:
            logger.error(f"❌ 初始化默认模型失败: {e}")

model_manager = ModelManager()
