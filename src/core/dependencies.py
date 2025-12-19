"""
认证依赖注入
"""
import logging
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from src.core.database import get_db
from src.core.auth import AuthService
from src.models.user import User

logger = logging.getLogger(__name__)


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> int:
    """
    获取当前用户ID（必需认证）
    从JWT token中提取username，然后查找用户并返回user_id
    """
    token = AuthService.get_token_from_header(request)
    if not token:
        logger.warning("⚠️ 请求缺少Authorization token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权，请先登录"
        )
    
    username = AuthService.verify_token(token)
    if username is None:
        logger.warning("⚠️ Token验证失败")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token无效或已过期，请重新登录"
        )
    
    # 通过username查找用户
    user = db.query(User).filter(User.username == username).first()
    if not user:
        logger.warning(f"⚠️ 用户 {username} 不存在")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在"
        )
    
    if not user.is_active:
        logger.warning(f"⚠️ 用户 {username} 已被禁用")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用"
        )
    
    logger.debug(f"✅ 用户 {username} (ID: {user.id}) 认证成功")
    return user.id


async def get_optional_user(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[int]:
    """
    获取当前用户ID（可选认证）
    如果token有效则返回user_id，否则返回None
    """
    token = AuthService.get_token_from_header(request)
    if not token:
        return None
    
    username = AuthService.verify_token(token)
    if username is None:
        return None
    
    # 通过username查找用户
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        return None
    
    return user.id

