"""
创建默认管理员用户脚本
在应用启动时调用，如果不存在用户则创建默认管理员
"""
import os
import sys
import logging
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import SessionLocal
from src.models.user import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_default_user():
    """创建默认管理员用户"""
    db = SessionLocal()
    try:
        # 检查是否已存在用户
        existing_user = db.query(User).first()
        if existing_user:
            logger.info(f"✅ 用户已存在，跳过创建默认用户。当前用户数: {db.query(User).count()}")
            return
        
        # 从环境变量读取默认用户名和密码
        admin_username = os.getenv("ADMIN_USERNAME", "admin").strip()
        admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
        
        if not admin_password:
            logger.warning("⚠️ ADMIN_PASSWORD 环境变量未设置，无法创建默认用户")
            logger.warning("   请设置 ADMIN_PASSWORD 环境变量后重启应用")
            return
        
        # bcrypt 限制密码长度不超过 72 字节，清理并截断
        admin_password = admin_password.strip()
        password_bytes = admin_password.encode('utf-8')
        if len(password_bytes) > 72:
            logger.warning(f"⚠️ 密码长度超过 72 字节（当前: {len(password_bytes)}），将被截断")
            # 按字节截断，确保不会截断多字节字符
            admin_password = password_bytes[:72].decode('utf-8', errors='ignore')
        
        logger.info(f"📝 准备创建用户: {admin_username}, 密码长度: {len(admin_password.encode('utf-8'))} 字节")
        
        # 创建默认管理员用户
        hashed_password = User.hash_password(admin_password)
        default_user = User(
            username=admin_username,
            email=None,
            hashed_password=hashed_password,
            is_active=True
        )
        
        db.add(default_user)
        db.commit()
        logger.info(f"✅ 成功创建默认管理员用户: {admin_username} (ID: {default_user.id})")
        
    except Exception as e:
        logger.error(f"❌ 创建默认用户失败: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_default_user()

