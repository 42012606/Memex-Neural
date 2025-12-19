"""
配置管理 API 端点
统一使用 ai_models 表管理 Router/Reasoning/Retrieval 配置
"""
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from src.core.database import get_db
from src.core.model_manager import model_manager
from src.models.ai_config import AIModel
from src.core.config_definitions import get_all_definitions
from src.core.config_manager import config_manager


router = APIRouter()
logger = logging.getLogger(__name__)


# --- Request Models ---

class ModelConfigRequest(BaseModel):
    """模型配置请求"""
    name: str
    provider: str
    model_id: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    is_active: bool = True
    priority: int = 0
    config: Optional[Dict[str, Any]] = None


class ModelPriority(BaseModel):
    id: int
    priority: int

class ReorderRequest(BaseModel):
    """排序请求"""
    models: List[ModelPriority]  # [{"id": 1, "priority": 0}, ...]


class WebhookTestRequest(BaseModel):
    webhook_url: str
    event_type: str = "test"
    payload: Dict[str, Any] = {"message": "Test notification from Memex"}

class ConfigBatchUpdateRequest(BaseModel):
    """Batch update format: {"system.debug_mode": true, ...} or {"system": {...}}"""
    values: Dict[str, Any]



# --- Models List Endpoint (for chat window) ---

@router.get("/config/models")
async def get_available_models(db: Session = Depends(get_db)):
    """获取所有推理模型列表（供聊天窗口选择）"""
    try:
        models = model_manager.get_reasoning_models(db)
        
        models_list = []
        for m in models:
            # 根据模型ID判别图标
            icon = "smart_toy"
            icon_color = "text-gray-400"
            
            mid = m.model_id.lower()
            if "gemini" in mid:
                icon = "bolt"
                icon_color = "text-yellow-400"
            elif "gpt" in mid:
                icon = "psychology"
                icon_color = "text-purple-400"
            elif "claude" in mid:
                icon = "auto_awesome"
                icon_color = "text-orange-400"
            elif "qwen" in mid:
                icon = "translate"
                icon_color = "text-blue-400"
            elif "deepseek" in mid:
                icon = "code"
                icon_color = "text-cyan-400"
            
            models_list.append({
                "value": str(m.id),  # 使用模型ID作为value
                "name": m.name,
                "model_id": m.model_id,
                "provider": m.provider,
                "description": f"{m.provider} - {m.model_id}",
                "icon": icon,
                "iconColor": icon_color
            })
        
        # 如果没有配置推理模型，返回默认选项
        if not models_list:
            models_list.append({
                "value": None,
                "name": "Default",
                "description": "No models configured",
                "icon": "settings",
                "iconColor": "text-gray-400"
            })
        
        return {
            "status": "ok",
            "models": models_list
        }
    except Exception as e:
        logger.error(f"获取模型列表失败: {e}")
        return {
            "status": "error",
            "models": [{
                "value": None,
                "name": "System Default (Error Loading)",
                "description": "Check logs",
                "icon": "error",
                "iconColor": "text-red-400"
            }]
        }


# --- Router Agent Endpoints (列表模式，类似 Reasoning) ---

@router.get("/config/router")
async def get_router_models(db: Session = Depends(get_db)):
    """获取所有Router模型列表"""
    try:
        models = model_manager.get_active_models(db, agent_type="router")
        models_list = []
        for m in models:
            models_list.append({
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "model_id": m.model_id,
                "api_key": m.api_key,
                "base_url": m.base_url,
                "is_active": m.is_active,
                "priority": m.priority,
                "config": m.config or {}
            })
        # 按 priority 排序
        models_list.sort(key=lambda x: x["priority"])
        return {
            "status": "ok",
            "models": models_list
        }
    except Exception as e:
        logger.error(f"获取Router模型列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/router")
async def add_router_model(
    request: ModelConfigRequest,
    db: Session = Depends(get_db)
):
    """添加Router模型"""
    try:
        model_data = request.dict()
        model_data["agent_type"] = "router"
        model_data["name"] = model_data.get("name", "Router Model")
        model_data["priority"] = model_data.get("priority", 0)
        
        model = model_manager.add_model(db, model_data)
        return {
            "status": "ok",
            "message": "Router模型已添加",
            "model": {
                "id": model.id,
                "name": model.name,
                "provider": model.provider,
                "model_id": model.model_id,
                "api_key": model.api_key,
                "base_url": model.base_url,
                "is_active": model.is_active,
                "priority": model.priority
            }
        }
    except Exception as e:
        logger.error(f"添加Router模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/router/{model_id}")
async def update_router_model(
    model_id: int,
    request: ModelConfigRequest,
    db: Session = Depends(get_db)
):
    """更新Router模型"""
    try:
        model = model_manager.get_model(db, model_id)
        if not model or model.agent_type != "router":
            raise HTTPException(status_code=404, detail="Router模型不存在")
        
        model_data = request.dict()
        model.name = model_data.get("name", model.name)
        model.provider = model_data.get("provider", model.provider)
        model.model_id = model_data.get("model_id", model.model_id)
        if "api_key" in model_data:
            model.api_key = model_data["api_key"]
        if "base_url" in model_data:
            model.base_url = model_data["base_url"]
        if "is_active" in model_data:
            model.is_active = model_data["is_active"]
        
        db.commit()
        db.refresh(model)
        
        return {
            "status": "ok",
            "message": "Router模型已更新",
            "model": {
                "id": model.id,
                "name": model.name,
                "provider": model.provider,
                "model_id": model.model_id,
                "api_key": model.api_key,
                "base_url": model.base_url,
                "is_active": model.is_active,
                "priority": model.priority
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新Router模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/config/router/{model_id}")
async def delete_router_model(model_id: int, db: Session = Depends(get_db)):
    """删除Router模型"""
    try:
        model = model_manager.get_model(db, model_id)
        if not model or model.agent_type != "router":
            raise HTTPException(status_code=404, detail="Router模型不存在")
        
        db.delete(model)
        db.commit()
        
        return {"status": "ok", "message": "Router模型已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除Router模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/router/reorder")
async def reorder_router_models(
    request: ReorderRequest,
    db: Session = Depends(get_db)
):
    """重新排序Router模型（更新优先级）"""
    try:
        for item in request.models:
            model = model_manager.get_model(db, item.id)
            if model and model.agent_type == "router":
                model.priority = item.priority
        
        db.commit()
        return {"status": "ok", "message": "Router模型优先级已更新"}
    except Exception as e:
        logger.error(f"更新Router模型优先级失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Reasoning Agent Endpoints ---

@router.get("/config/reasoning")
async def get_reasoning_models(db: Session = Depends(get_db)):
    """获取所有推理模型列表"""
    try:
        models = model_manager.get_reasoning_models(db)
        logger.debug(f"获取到 {len(models)} 个推理模型")
        result = []
        for m in models:
            try:
                # 处理 config 字段：如果是字典则直接使用，如果是字符串则解析
                config_value = m.config
                if isinstance(config_value, str):
                    try:
                        import json
                        config_value = json.loads(config_value)
                    except:
                        config_value = {}
                elif config_value is None:
                    config_value = {}
                
                # 处理 created_at：确保正确序列化
                created_at_value = None
                if m.created_at:
                    if hasattr(m.created_at, 'isoformat'):
                        created_at_value = m.created_at.isoformat()
                    else:
                        created_at_value = str(m.created_at)
                
                result.append({
                    "id": m.id,
                    "name": m.name or "",
                    "provider": m.provider or "",
                    "model_id": m.model_id or "",
                    "api_key": m.api_key or "",
                    "base_url": m.base_url or "",
                    "is_active": m.is_active if m.is_active is not None else True,
                    "priority": m.priority if m.priority is not None else 0,
                    "config": config_value,
                    "created_at": created_at_value
                })
            except Exception as model_error:
                logger.error(f"处理模型 {m.id if hasattr(m, 'id') else 'unknown'} 时出错: {model_error}", exc_info=True)
                continue
        
        return {
            "status": "ok",
            "models": result
        }
    except Exception as e:
        logger.error(f"获取推理模型列表失败: {e}", exc_info=True)
        import traceback
        logger.error(f"详细错误: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"获取推理模型列表失败: {str(e)}")


@router.post("/config/reasoning")
async def add_reasoning_model(
    request: ModelConfigRequest,
    db: Session = Depends(get_db)
):
    """添加推理模型"""
    try:
        model_data = request.dict()
        model_data["agent_type"] = "reasoning"
        model = model_manager.add_model(db, model_data)
        return {
            "status": "ok",
            "message": "推理模型已添加",
            "id": model.id
        }
    except Exception as e:
        logger.error(f"添加推理模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/reasoning/reorder")
async def reorder_reasoning_models(
    request: ReorderRequest,
    db: Session = Depends(get_db)
):
    """批量更新推理模型优先级（拖动排序）"""
    try:
        if not request.models:
            raise HTTPException(status_code=422, detail="models 不能为空")

        # 输入校验：id/priority 必须为数字且唯一
        normalized = []
        seen_ids = set()
        for idx, item in enumerate(request.models):
            if item.id in seen_ids:
                raise HTTPException(status_code=422, detail=f"重复的模型ID: {item.id}")
            seen_ids.add(item.id)
            try:
                normalized.append({"id": int(item.id), "priority": int(idx)})
            except ValueError:
                raise HTTPException(status_code=422, detail="id/priority 必须为数字")

        success = model_manager.reorder_models(db, "reasoning", normalized)
        if success:
            return {
                "status": "ok",
                "message": "优先级已更新"
            }
        else:
            raise HTTPException(status_code=500, detail="更新优先级失败")
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"更新优先级失败: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"更新优先级失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/reasoning/{model_id}")
async def update_reasoning_model(
    model_id: int,
    request: ModelConfigRequest,
    db: Session = Depends(get_db)
):
    """更新推理模型"""
    try:
        model = model_manager.get_model(db, model_id)
        if not model or model.agent_type != "reasoning":
            raise HTTPException(status_code=404, detail="推理模型不存在")
        
        updated = model_manager.update_model(db, model_id, request.dict())
        if not updated:
            raise HTTPException(status_code=404, detail="模型不存在")
        
        return {
            "status": "ok",
            "message": "推理模型已更新"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新推理模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/config/reasoning/{model_id}")
async def delete_reasoning_model(model_id: int, db: Session = Depends(get_db)):
    """删除推理模型"""
    try:
        model = model_manager.get_model(db, model_id)
        if not model or model.agent_type != "reasoning":
            raise HTTPException(status_code=404, detail="推理模型不存在")
        
        success = model_manager.delete_model(db, model_id)
        if not success:
            raise HTTPException(status_code=404, detail="模型不存在")
        
        return {
            "status": "ok",
            "message": "推理模型已删除"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除推理模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# --- Retrieval Agent Endpoints ---

@router.get("/config/retrieval")
async def get_retrieval_config(db: Session = Depends(get_db)):
    """获取Retrieval Agent配置"""
    try:
        retrieval_model = model_manager.get_retrieval_config(db)
        if retrieval_model:
            return {
                "status": "ok",
                "config": {
                    "id": retrieval_model.id,
                    "base_url": retrieval_model.base_url,  # 向量服务地址
                    "api_key": retrieval_model.api_key,
                    "is_active": retrieval_model.is_active
                }
            }
        else:
            # 向后兼容：尝试从 system_config 读取
            from src.core.config_manager import config_manager
            legacy_config = config_manager.get_config("retrieval", db=db)
            return {
                "status": "ok",
                "config": legacy_config or {}
            }
    except Exception as e:
        logger.error(f"获取Retrieval配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/retrieval")
async def update_retrieval_config(
    request: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """更新Retrieval Agent配置（向量服务地址）"""
    try:
        # 构建模型数据
        model_data = {
            "agent_type": "retrieval",
            "name": "Retrieval Agent",
            "provider": "remote",  # 占位符
            "model_id": "vector-service",  # 占位符
            "base_url": request.get("base_url", ""),
            "api_key": request.get("api_key"),
            "is_active": True,
            "priority": 0
        }
        
        model = model_manager.add_model(db, model_data)  # add_model会检查并更新已存在的retrieval
        return {
            "status": "ok",
            "message": "Retrieval配置已更新",
            "config": {
                "id": model.id,
                "base_url": model.base_url,
                "api_key": model.api_key,
                "is_active": model.is_active
            }
        }
    except Exception as e:
        logger.error(f"更新Retrieval配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Audio Config Endpoints ---

@router.get("/config/audio")
async def get_audio_config(db: Session = Depends(get_db)):
    """获取所有Audio配置 (TTS/STT)"""
    try:
        from src.core.config_manager import config_manager
        audio_config = config_manager.get_config("audio", db=db)
        return {
            "status": "ok",
            "config": audio_config or {}
        }
    except Exception as e:
        logger.error(f"获取Audio配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))




# --- Schema-Driven Config Endpoints (Phase 5.4) ---

@router.get("/config/schema")
async def get_config_schema():
    """获取配置 UI 的定义 Schema"""
    try:
        definitions = get_all_definitions()
        # Convert pydantic models to dicts
        return {
            "status": "ok",
            "schema": [group.dict() for group in definitions]
        }
    except Exception as e:
        logger.error(f"Failed to load config schema: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/config/values")
async def get_config_values(db: Session = Depends(get_db)):
    """获取当前的配置值"""
    try:
        all_configs = config_manager.get_all_config(db)
        return {
            "status": "ok",
            "values": all_configs
        }
    except Exception as e:
        logger.error(f"Failed to load config values: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/config/values")
async def update_config_values(
    request: ConfigBatchUpdateRequest,
    db: Session = Depends(get_db)
):
    """Batch update config values"""
    try:
        updates = request.values
        # Group updates by section
        grouped_updates = {}
        
        # Determine format: Flattened "system.debug" vs Nested "system": {"debug": ...}
        for key, value in updates.items():
            if "." in key:
                section, subkey = key.split(".", 1)
            else:
                section = key
                subkey = None
            
            if section not in grouped_updates:
                grouped_updates[section] = {}
            
            if subkey:
                grouped_updates[section][subkey] = value
            elif isinstance(value, dict):
                # If entire section dict is passed
                grouped_updates[section] = value
        
        # Update ConfigManager
        updated_sections = []
        for section, new_values in grouped_updates.items():
            # Get existing to merge
            current = config_manager.get_config(section, db)
            current.update(new_values)
            
            success = config_manager.update_config(section, current, db, description=f"Updated via Settings UI")
            if success:
                updated_sections.append(section)
        
        return {
            "status": "ok",
            "message": f"Updated sections: {', '.join(updated_sections)}",
            "updated": updated_sections
        }
    except Exception as e:
        logger.error(f"Batch config update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/config/test-webhook")
async def test_webhook(request: WebhookTestRequest):
    """Test webhook connectivity"""
    import requests
    try:
        response = requests.post(
            request.webhook_url, 
            json={
                "event": request.event_type,
                "data": request.payload
            }, 
            timeout=5
        )
        return {
            "status": "ok",
            "webhook_status": response.status_code,
            "response_text": response.text[:200]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }



# --- Legacy Compatibility Endpoints ---

@router.get("/config")
async def get_all_config(db: Session = Depends(get_db)):
    """获取所有配置（向后兼容）"""
    try:
        router_config = await get_router_models(db)
        reasoning_config = await get_reasoning_models(db)
        retrieval_config = await get_retrieval_config(db)
        
        return {
            "status": "ok",
            "config": {
                "router": router_config.get("models", []),
                "reasoning": reasoning_config.get("models", []),
                "retrieval": retrieval_config.get("config", {})
            }
        }
    except Exception as e:
        logger.error(f"获取配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Vector Service Test Endpoint ---

@router.post("/config/test")
async def test_model_connection(
    request: ModelConfigRequest,
    db: Session = Depends(get_db)
):
    """测试单个模型连接"""
    from starlette.concurrency import run_in_threadpool
    from src.services.ai_service import AIService
    from src.core.error_translator import translate_ai_error
    
    try:
        # 构造临时模型对象
        model = AIModel(
            name=request.name,
            provider=request.provider,
            model_id=request.model_id,
            api_key=request.api_key,
            base_url=request.base_url,
            config=request.config
        )
        
        # 使用 AIService (这里我们需要根据 provider 简单判断 service_type，或者默认通用)
        # 大部分模型可以用 generic/router/reasoning 逻辑测试
        # 为了通用性，我们尝试实例化一个 provider 并调用 chat
        
        # 简单推断 service_type
        service_type = "reasoning" # 默认
        if "vision" in request.provider or "vision" in request.name.lower():
            service_type = "vision"
        
        ai_service = AIService(service_type=service_type)
        
        try:
            provider = ai_service._build_provider(model, db)
            
            # 优先使用 check_health 接口 (支持 TTS/STT/Embedding 等特殊模型)
            if hasattr(provider, "check_health"):
                health = await run_in_threadpool(provider.check_health)
                if health.get("status") == "ok":
                    return {
                        "status": "ok",
                        "message": health.get("message", "Connection successful")
                    }
                else:
                    return {
                        "status": "error",
                        "message": health.get("message", "Health check failed")
                    }
            
            # Fallback: Ping 测试 (仅适用于 Chat 模型)
            test_query = "Si" # Shortest possible token for some tokenizers, 'Hi' is also good
            test_reply = await run_in_threadpool(provider.chat, test_query, "")
            
            if ai_service._is_error_reply(test_reply):
                return {
                    "status": "error",
                    "message": translate_ai_error(test_reply)
                }
            
            return {
                "status": "ok",
                "message": "Connection successful"
            }
            
        except Exception as ve:
            return {
                "status": "error",
                "message": translate_ai_error(str(ve))
            }

    except Exception as e:
        logger.error(f"连接测试失败: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@router.get("/config/models/health")
async def check_models_health(db: Session = Depends(get_db)):
    """检查模型池健康状态（API Key 有效性和连接状态）"""
    from starlette.concurrency import run_in_threadpool
    from src.services.ai_service import AIService
    from src.core.model_manager import model_manager
    from src.core.error_translator import translate_ai_error
    import asyncio
    
    async def test_model(model, service_type: str):
        """测试单个模型的健康状态（真实 API Ping）"""
        try:
            ai_service = AIService(service_type=service_type)
            
            # 1. 检查配置存在性
            try:
                provider = ai_service._build_provider(model, db)
                has_api_key = bool(model.api_key or (hasattr(provider, 'api_key') and provider.api_key))
                if not has_api_key:
                    return {
                        "id": model.id,
                        "name": model.name,
                        "provider": model.provider,
                        "model_id": model.model_id,
                        "status": "missing_api_key",
                        "error": "API Key 未配置"
                    }
            except ValueError as ve:
                return {
                    "id": model.id,
                    "name": model.name,
                    "provider": model.provider,
                    "model_id": model.model_id,
                    "status": "config_error",
                    "error": translate_ai_error(str(ve))
                }
            
            # 2. 真实 API Ping
            try:
                # 优先使用 check_health (支持各类模型)
                if hasattr(provider, "check_health"):
                    health = await run_in_threadpool(provider.check_health)
                    if health.get("status") == "ok":
                        return {
                            "id": model.id,
                            "name": model.name,
                            "provider": model.provider,
                            "model_id": model.model_id,
                            "status": "healthy",
                            "error": None
                        }
                    else:
                        return {
                            "id": model.id,
                            "name": model.name,
                            "provider": model.provider,
                            "model_id": model.model_id,
                            "status": "error",
                            "error": health.get("message", "Health check failed")
                        }

                # Fallback: Chat Ping
                test_query = "Hi"
                test_reply = await run_in_threadpool(provider.chat, test_query, "")
                
                if ai_service._is_error_reply(test_reply):
                    return {
                        "id": model.id,
                        "name": model.name,
                        "provider": model.provider,
                        "model_id": model.model_id,
                        "status": "error",
                        "error": translate_ai_error(test_reply)
                    }
                
                return {
                    "id": model.id,
                    "name": model.name,
                    "provider": model.provider,
                    "model_id": model.model_id,
                    "status": "healthy",
                    "error": None
                }
            except Exception as api_error:
                error_msg = translate_ai_error(str(api_error))
                return {
                    "id": model.id,
                    "name": model.name,
                    "provider": model.provider,
                    "model_id": model.model_id,
                    "status": "error",
                    "error": error_msg
                }
        except Exception as e:
            return {
                "id": model.id,
                "name": model.name,
                "provider": model.provider,
                "model_id": model.model_id,
                "status": "error",
                "error": translate_ai_error(str(e))
            }
    
    try:
        health_status = {
            "router": [],
            "reasoning": [],
            "overall": {"healthy": 0, "errors": 0, "total": 0}
        }
        
        # 检查 Router 模型
        # To avoid duplicating logic, we could call the new endpoint logic, but for batch performance async is better here
        # So keeping the async batch logic
        router_models = model_manager.get_active_models(db, agent_type="router")
        router_tasks = [test_model(m, "router") for m in router_models]
        router_results = await asyncio.gather(*router_tasks, return_exceptions=True)
        for result in router_results:
            if isinstance(result, Exception):
                health_status["router"].append({
                    "status": "error",
                    "error": translate_ai_error(str(result))
                })
                health_status["overall"]["errors"] += 1
            else:
                health_status["router"].append(result)
                if result["status"] == "healthy":
                    health_status["overall"]["healthy"] += 1
                else:
                    health_status["overall"]["errors"] += 1
            health_status["overall"]["total"] += 1
        
        # 检查 Reasoning 模型
        reasoning_models = model_manager.get_active_models(db, agent_type="reasoning")
        reasoning_tasks = [test_model(m, "reasoning") for m in reasoning_models]
        reasoning_results = await asyncio.gather(*reasoning_tasks, return_exceptions=True)
        for result in reasoning_results:
            if isinstance(result, Exception):
                health_status["reasoning"].append({
                    "status": "error",
                    "error": translate_ai_error(str(result))
                })
                health_status["overall"]["errors"] += 1
            else:
                health_status["reasoning"].append(result)
                if result["status"] == "healthy":
                    health_status["overall"]["healthy"] += 1
                else:
                    health_status["overall"]["errors"] += 1
            health_status["overall"]["total"] += 1
        
        return health_status
    except Exception as e:
        logger.error(f"健康检查失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"健康检查失败: {str(e)}")


@router.post("/config/retrieval/test")
async def test_vector_service(db: Session = Depends(get_db)):
    """测试向量服务连接"""
    try:
        from src.services.ai_service import AIService
        
        # 使用 AIService 进行向量化测试
        ai_service = AIService()
        test_text = "这是一个测试文本"
        try:
            vector = ai_service.embed_text(test_text, db_session=db)
            vector_dim = len(vector) if vector else 0
            
            return {
                "status": "ok",
                "message": "向量服务连接正常",
                "available": True,
                "vector_dimension": vector_dim,
                "dimension_match": vector_dim == 1024,  # 更新为 1024 维
                "test_result": {
                    "text": test_text,
                    "vector_length": vector_dim
                }
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"向量服务测试失败: {str(e)}",
                "available": False,
                "error": str(e)
            }
    except Exception as e:
        logger.error(f"测试向量服务失败: {e}")
        return {
            "status": "error",
            "message": f"测试失败: {str(e)}",
            "available": False,
            "error": str(e)
        }


# --- Vision Agent Endpoints ---

@router.get("/config/vision")
async def get_vision_models(db: Session = Depends(get_db)):
    """获取所有Vision模型列表"""
    try:
        models = model_manager.get_active_models(db, agent_type="vision")
        models_list = []
        for m in models:
            models_list.append({
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "model_id": m.model_id,
                "api_key": m.api_key,
                "is_active": m.is_active,
                "priority": m.priority,
                "config": m.config or {}
            })
        models_list.sort(key=lambda x: x["priority"])
        return {
            "status": "ok",
            "models": models_list
        }
    except Exception as e:
        logger.error(f"获取Vision模型列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/vision")
async def add_vision_model(
    request: ModelConfigRequest,
    db: Session = Depends(get_db)
):
    """添加Vision模型"""
    try:
        model_data = request.dict()
        model_data["agent_type"] = "vision"
        model_data["name"] = model_data.get("name", "Vision Model")
        model_data["priority"] = model_data.get("priority", 0)
        
        model = model_manager.add_model(db, model_data)
        return {
            "status": "ok",
            "message": "Vision模型已添加",
            "model": {
                "id": model.id,
                "name": model.name,
                "provider": model.provider,
                "model_id": model.model_id,
                "api_key": model.api_key,
                "is_active": model.is_active,
                "priority": model.priority
            }
        }
    except Exception as e:
        logger.error(f"添加Vision模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/vision/{model_id}")
async def update_vision_model(
    model_id: int,
    request: ModelConfigRequest,
    db: Session = Depends(get_db)
):
    """更新Vision模型"""
    try:
        model = model_manager.get_model(db, model_id)
        if not model or model.agent_type != "vision":
            raise HTTPException(status_code=404, detail="Vision模型不存在")
        
        model_data = request.dict()
        updated = model_manager.update_model(db, model_id, model_data)
        if not updated:
            raise HTTPException(status_code=404, detail="模型不存在")
        
        return {
            "status": "ok",
            "message": "Vision模型已更新"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新Vision模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/config/vision/{model_id}")
async def delete_vision_model(model_id: int, db: Session = Depends(get_db)):
    """删除Vision模型"""
    try:
        model = model_manager.get_model(db, model_id)
        if not model or model.agent_type != "vision":
            raise HTTPException(status_code=404, detail="Vision模型不存在")
        
        success = model_manager.delete_model(db, model_id)
        if not success:
            raise HTTPException(status_code=404, detail="模型不存在")
        
        return {"status": "ok", "message": "Vision模型已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除Vision模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# --- Voice (TTS) Agent Endpoints ---

@router.get("/config/voice")
async def get_voice_models(db: Session = Depends(get_db)):
    """获取所有Voice (TTS)模型列表"""
    try:
        models = model_manager.get_active_models(db, agent_type="voice")
        models_list = []
        for m in models:
            models_list.append({
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "model_id": m.model_id,
                "api_key": m.api_key,
                "is_active": m.is_active,
                "priority": m.priority,
                "config": m.config or {}
            })
        models_list.sort(key=lambda x: x["priority"])
        return {
            "status": "ok",
            "models": models_list
        }
    except Exception as e:
        logger.error(f"获取Voice模型列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/voice")
async def add_voice_model(
    request: ModelConfigRequest,
    db: Session = Depends(get_db)
):
    """添加Voice模型"""
    try:
        model_data = request.dict()
        model_data["agent_type"] = "voice"
        model_data["name"] = model_data.get("name", "Voice Model")
        model_data["priority"] = model_data.get("priority", 0)
        
        model = model_manager.add_model(db, model_data)
        return {
            "status": "ok",
            "message": "Voice模型已添加",
            "model": {
                "id": model.id,
                "name": model.name,
                "provider": model.provider,
                "model_id": model.model_id,
                "api_key": model.api_key,
                "is_active": model.is_active,
                "priority": model.priority
            }
        }
    except Exception as e:
        logger.error(f"添加Voice模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/voice/reorder")
async def reorder_voice_models(
    request: ReorderRequest,
    db: Session = Depends(get_db)
):
    """批量更新Voice模型优先级"""
    try:
        if not request.models:
            raise HTTPException(status_code=422, detail="models 不能为空")

        normalized = []
        seen_ids = set()
        for idx, item in enumerate(request.models):
            if item.id in seen_ids:
                continue
            seen_ids.add(item.id)
            normalized.append({"id": int(item.id), "priority": int(idx)})

        success = model_manager.reorder_models(db, "voice", normalized)
        if success:
            return {"status": "ok", "message": "优先级已更新"}
        else:
            raise HTTPException(status_code=500, detail="更新优先级失败")
    except Exception as e:
        logger.error(f"更新Voice模型优先级失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/voice/{model_id}")
async def update_voice_model(
    model_id: int,
    request: ModelConfigRequest,
    db: Session = Depends(get_db)
):
    """更新Voice模型"""
    try:
        model = model_manager.get_model(db, model_id)
        if not model or model.agent_type != "voice":
            raise HTTPException(status_code=404, detail="Voice模型不存在")
        
        updated = model_manager.update_model(db, model_id, request.dict())
        if not updated:
            raise HTTPException(status_code=404, detail="模型不存在")
        
        return {
            "status": "ok",
            "message": "Voice模型已更新"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新Voice模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/config/voice/{model_id}")
async def delete_voice_model(model_id: int, db: Session = Depends(get_db)):
    """删除Voice模型"""
    try:
        model = model_manager.get_model(db, model_id)
        if not model or model.agent_type != "voice":
            raise HTTPException(status_code=404, detail="Voice模型不存在")
        
        success = model_manager.delete_model(db, model_id)
        if not success:
            raise HTTPException(status_code=404, detail="模型不存在")
        
        return {"status": "ok", "message": "Voice模型已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除Voice模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# --- Hearing (STT) Agent Endpoints ---

@router.get("/config/hearing")
async def get_hearing_models(db: Session = Depends(get_db)):
    """获取所有Hearing (STT)模型列表"""
    try:
        models = model_manager.get_active_models(db, agent_type="hearing")
        models_list = []
        for m in models:
            models_list.append({
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "model_id": m.model_id,
                "api_key": m.api_key,
                "is_active": m.is_active,
                "priority": m.priority,
                "config": m.config or {}
            })
        models_list.sort(key=lambda x: x["priority"])
        return {
            "status": "ok",
            "models": models_list
        }
    except Exception as e:
        logger.error(f"获取Hearing模型列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/hearing")
async def add_hearing_model(
    request: ModelConfigRequest,
    db: Session = Depends(get_db)
):
    """添加Hearing模型"""
    try:
        model_data = request.dict()
        model_data["agent_type"] = "hearing"
        model_data["name"] = model_data.get("name", "Hearing Model")
        model_data["priority"] = model_data.get("priority", 0)
        
        model = model_manager.add_model(db, model_data)
        return {
            "status": "ok",
            "message": "Hearing模型已添加",
            "model": {
                "id": model.id,
                "name": model.name,
                "provider": model.provider,
                "model_id": model.model_id,
                "api_key": model.api_key,
                "is_active": model.is_active,
                "priority": model.priority
            }
        }
    except Exception as e:
        logger.error(f"添加Hearing模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/hearing/reorder")
async def reorder_hearing_models(
    request: ReorderRequest,
    db: Session = Depends(get_db)
):
    """批量更新Hearing模型优先级"""
    try:
        if not request.models:
            raise HTTPException(status_code=422, detail="models 不能为空")

        normalized = []
        seen_ids = set()
        for idx, item in enumerate(request.models):
            if item.id in seen_ids:
                continue
            seen_ids.add(item.id)
            normalized.append({"id": int(item.id), "priority": int(idx)})

        success = model_manager.reorder_models(db, "hearing", normalized)
        if success:
            return {"status": "ok", "message": "优先级已更新"}
        else:
            raise HTTPException(status_code=500, detail="更新优先级失败")
    except Exception as e:
        logger.error(f"更新Hearing模型优先级失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/hearing/{model_id}")
async def update_hearing_model(
    model_id: int,
    request: ModelConfigRequest,
    db: Session = Depends(get_db)
):
    """更新Hearing模型"""
    try:
        model = model_manager.get_model(db, model_id)
        if not model or model.agent_type != "hearing":
            raise HTTPException(status_code=404, detail="Hearing模型不存在")
        
        updated = model_manager.update_model(db, model_id, request.dict())
        if not updated:
            raise HTTPException(status_code=404, detail="模型不存在")
        
        return {
            "status": "ok",
            "message": "Hearing模型已更新"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新Hearing模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/config/hearing/{model_id}")
async def delete_hearing_model(model_id: int, db: Session = Depends(get_db)):
    """删除Hearing模型"""
    try:
        model = model_manager.get_model(db, model_id)
        if not model or model.agent_type != "hearing":
            raise HTTPException(status_code=404, detail="Hearing模型不存在")
        
        success = model_manager.delete_model(db, model_id)
        if not success:
            raise HTTPException(status_code=404, detail="模型不存在")
        
        return {"status": "ok", "message": "Hearing模型已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除Hearing模型失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))




# --- Memory (Embedding) Agent Endpoints ---

@router.get("/config/memory")
async def get_memory_config(db: Session = Depends(get_db)):
    """获取Memory (Embedding)配置"""
    try:
        embedding_models = model_manager.get_active_models(db, agent_type="embedding")
        if embedding_models and len(embedding_models) > 0:
            model = embedding_models[0]  # Embedding通常只有一个
            return {
                "status": "ok",
                "config": {
                    "id": model.id,
                    "provider": model.provider,
                    "model_id": model.model_id,
                    "api_key": model.api_key,
                    "is_active": model.is_active
                }
            }
        else:
            return {
                "status": "ok",
                "config": {
                    "provider": "dashscope",
                    "model_id": "",
                    "api_key": ""
                }
            }
    except Exception as e:
        logger.error(f"获取Memory配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/memory")
async def update_memory_config(
    request: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """更新Memory (Embedding)配置"""
    try:
        # 构建模型数据
        model_data = {
            "agent_type": "embedding",
            "name": "Embedding Model",
            "provider": request.get("provider", "dashscope"),
            "model_id": request.get("model_id", ""),
            "api_key": request.get("api_key"),
            "is_active": True,
            "priority": 0
        }
        
        # Embedding只允许1条记录，检查是否已存在
        from src.models.ai_config import AIModel
        existing = db.query(AIModel).filter(AIModel.agent_type == "embedding").first()
        if existing:
            model = model_manager.update_model(db, existing.id, model_data)
        else:
            model = model_manager.add_model(db, model_data)
        
        db.commit()
        db.refresh(model)
        
        return {
            "status": "ok",
            "message": "Memory配置已更新",
            "config": {
                "id": model.id,
                "provider": model.provider,
                "model_id": model.model_id,
                "api_key": model.api_key,
                "is_active": model.is_active
            }
        }
    except Exception as e:
        logger.error(f"更新Memory配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新Memory配置失败: {str(e)}")