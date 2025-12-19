"""
用户管理API端点
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# --- Pydantic Models ---

class UserCreateRequest(BaseModel):
    """创建用户请求"""
    username: str
    password: str
    email: Optional[str] = None


class UserUpdateRequest(BaseModel):
    """更新用户请求"""
    username: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None


class PasswordChangeRequest(BaseModel):
    """修改密码请求"""
    old_password: str
    new_password: str


class UserResponse(BaseModel):
    """用户响应"""
    id: int
    username: str
    email: Optional[str]
    is_active: bool
    created_at: str
    
    class Config:
        from_attributes = True


# --- Helper Functions ---

def is_admin(user_id: int, db: Session) -> bool:
    """检查用户是否为管理员（ID为1的用户）"""
    # 简单实现：ID为1的用户是管理员
    # 未来可以扩展为在User模型中添加is_admin字段
    return user_id == 1


# --- API Endpoints ---

@router.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取用户列表
    管理员可以查看所有用户，普通用户只能查看自己的信息
    """
    if not is_admin(current_user_id, db):
        # 普通用户只返回自己的信息
        user = db.query(User).filter(User.id == current_user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        return [UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            is_active=user.is_active,
            created_at=user.created_at.isoformat() if user.created_at else ""
        )]
    
    # 管理员返回所有用户
    users = db.query(User).all()
    return [UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else ""
    ) for user in users]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreateRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    创建新用户
    仅管理员可以创建用户
    """
    if not is_admin(current_user_id, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以创建用户"
        )
    
    # 检查用户名是否已存在
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )
    
    # 检查邮箱是否已存在（如果提供了邮箱）
    if user_data.email:
        existing_email = db.query(User).filter(User.email == user_data.email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被使用"
            )
    
    # 创建新用户
    hashed_password = User.hash_password(user_data.password)
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hashed_password,
        is_active=True
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    logger.info(f"✅ 管理员 {current_user_id} 创建了新用户: {new_user.username} (ID: {new_user.id})")
    
    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        email=new_user.email,
        is_active=new_user.is_active,
        created_at=new_user.created_at.isoformat() if new_user.created_at else ""
    )


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取用户信息
    管理员可以查看任何用户，普通用户只能查看自己的信息
    """
    if not is_admin(current_user_id, db) and user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问该用户信息"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else ""
    )


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdateRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    更新用户信息
    管理员可以更新任何用户，普通用户只能更新自己的信息（但不能修改is_active）
    """
    if not is_admin(current_user_id, db) and user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权修改该用户信息"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 普通用户不能修改is_active
    if not is_admin(current_user_id, db) and user_data.is_active is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="普通用户不能修改账户状态"
        )
    
    # 更新用户名（如果提供且不同）
    if user_data.username and user_data.username != user.username:
        # 检查新用户名是否已存在
        existing = db.query(User).filter(User.username == user_data.username).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已存在"
            )
        user.username = user_data.username
    
    # 更新邮箱（如果提供）
    if user_data.email is not None:
        if user_data.email != user.email:
            # 检查新邮箱是否已被使用
            existing = db.query(User).filter(User.email == user_data.email).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="邮箱已被使用"
                )
        user.email = user_data.email
    
    # 更新is_active（仅管理员）
    if is_admin(current_user_id, db) and user_data.is_active is not None:
        user.is_active = user_data.is_active
    
    db.commit()
    db.refresh(user)
    
    logger.info(f"✅ 用户 {current_user_id} 更新了用户 {user_id} 的信息")
    
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else ""
    )


@router.put("/users/{user_id}/password", status_code=status.HTTP_200_OK)
async def change_password(
    user_id: int,
    password_data: PasswordChangeRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    修改密码
    管理员可以修改任何用户的密码（不需要旧密码），普通用户只能修改自己的密码（需要提供旧密码）
    """
    if not is_admin(current_user_id, db) and user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权修改该用户密码"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 普通用户需要验证旧密码
    if not is_admin(current_user_id, db):
        if not user.verify_password(password_data.old_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="旧密码错误"
            )
    
    # 更新密码
    user.hashed_password = User.hash_password(password_data.new_password)
    db.commit()
    
    logger.info(f"✅ 用户 {current_user_id} 修改了用户 {user_id} 的密码")
    
    return {"message": "密码修改成功"}


@router.delete("/users/{user_id}", status_code=status.HTTP_200_OK)
async def delete_user(
    user_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除用户
    仅管理员可以删除用户，不能删除自己
    """
    if not is_admin(current_user_id, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以删除用户"
        )
    
    if user_id == current_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能删除自己的账户"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    db.delete(user)
    db.commit()
    
    logger.info(f"✅ 管理员 {current_user_id} 删除了用户 {user_id} ({user.username})")
    
    return {"message": "用户删除成功"}

