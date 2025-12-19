"""
JWT认证服务
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Request, HTTPException, status

logger = logging.getLogger(__name__)

# JWT配置
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "168"))  # 默认7天


class AuthService:
    """JWT认证服务"""
    
    @staticmethod
    def create_access_token(username: str) -> str:
        """生成JWT token（使用username作为标识）"""
        expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
        payload = {
            "sub": username,  # subject (用户名)
            "exp": expire,  # expiration
            "iat": datetime.utcnow(),  # issued at
        }
        token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        logger.info(f"✅ 为用户 {username} 生成JWT token，过期时间: {expire}")
        return token
    
    @staticmethod
    def verify_token(token: str) -> Optional[str]:
        """验证token并返回username"""
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            username: str = payload.get("sub")
            if username is None:
                logger.warning("⚠️ Token中缺少username")
                return None
            return username
        except JWTError as e:
            logger.warning(f"⚠️ Token验证失败: {e}")
            return None
    
    @staticmethod
    def get_token_from_header(request: Request) -> Optional[str]:
        """从Authorization header提取token"""
        authorization: str = request.headers.get("Authorization", "")
        if not authorization:
            return None
        
        # 支持 "Bearer <token>" 格式
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        
        return parts[1]

