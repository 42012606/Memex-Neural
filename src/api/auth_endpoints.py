"""
认证API端点
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel

from src.core.database import get_db
from src.core.auth import AuthService
from src.core.dependencies import get_current_user
from src.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)
security = HTTPBearer()


# --- Pydantic Models ---

class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str


class UserInfo(BaseModel):
    """用户信息"""
    id: int
    username: str
    email: Optional[str]
    is_active: bool
    
    class Config:
        from_attributes = True


# --- API Endpoints ---

@router.post("/auth/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
async def login(
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    用户登录
    验证用户名和密码，返回JWT token
    """
    logger.info(f"🔐 用户登录尝试: {login_data.username}")
    
    # 查找用户
    user = db.query(User).filter(User.username == login_data.username).first()
    if not user:
        logger.warning(f"⚠️ 用户不存在: {login_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 验证密码
    if not user.verify_password(login_data.password):
        logger.warning(f"⚠️ 密码错误: {login_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 检查用户是否激活
    if not user.is_active:
        logger.warning(f"⚠️ 用户已被禁用: {login_data.username}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用"
        )
    
    # 生成JWT token（使用username作为标识）
    token = AuthService.create_access_token(user.username)
    # Explicitly convert to string to ensure no bytes are passed to JSON response
    final_token = str(token) if token is not None else ""
    final_username = str(user.username) if user.username is not None else ""
    
    logger.info(f"Returning LoginResponse: token_type={type(final_token)}, username_type={type(final_username)}")
    
    return LoginResponse(
        access_token=final_token,
        token_type="bearer",
        user_id=user.id,
        username=final_username
    )


@router.post("/auth/logout", status_code=status.HTTP_200_OK)
async def logout(
    current_user_id: int = Depends(get_current_user)
):
    """
    用户登出（前端删除token即可，后端可选实现）
    """
    logger.info(f"👋 用户 {current_user_id} 登出")
    return {"message": "登出成功"}


@router.get("/auth/me", response_model=UserInfo, status_code=status.HTTP_200_OK)
async def get_current_user_info(
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取当前用户信息
    需要认证
    """
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    return UserInfo(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active
    )

