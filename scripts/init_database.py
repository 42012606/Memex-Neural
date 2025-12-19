#!/usr/bin/env python3
"""
数据库重新初始化后的配置脚本
在数据库重新初始化后运行此脚本，重新创建必要的表结构
"""
import sys
import os
from pathlib import Path

# 添加项目根目录到路径（不是 src 目录）
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 切换到项目根目录
os.chdir(project_root)

# 检测运行环境：检查是否在 Docker 容器内
is_docker = os.path.exists("/.dockerenv") or os.getenv("DOCKER_CONTAINER") == "true"

# 尝试加载 .env 文件（如果存在）
env_file = project_root / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
        print(f"Loaded environment variables from .env")
    except ImportError:
        print("Warning: python-dotenv not installed, skipping .env loading")
        print("Make sure environment variables are set manually")

# 如果在本地运行（非 Docker），强制设置 POSTGRES_HOST 为 localhost
if not is_docker:
    # 强制覆盖，即使 .env 中设置了 "db"
    os.environ["POSTGRES_HOST"] = "localhost"
    print("Running locally: Set POSTGRES_HOST to localhost")
    
    # 如果其他环境变量未设置，使用默认值
    if os.getenv("POSTGRES_USER") is None:
        os.environ["POSTGRES_USER"] = "memex"
    if os.getenv("POSTGRES_PASSWORD") is None:
        os.environ["POSTGRES_PASSWORD"] = "memex_password_secure"
    if os.getenv("POSTGRES_DB") is None:
        os.environ["POSTGRES_DB"] = "memex_core"
    if os.getenv("POSTGRES_PORT") is None:
        os.environ["POSTGRES_PORT"] = "5432"
else:
    print("Running in Docker container: Using POSTGRES_HOST from environment")

# 打印连接信息（用于调试）
print(f"Database connection info:")
print(f"  Host: {os.getenv('POSTGRES_HOST', 'db')}")
print(f"  Port: {os.getenv('POSTGRES_PORT', '5432')}")
print(f"  Database: {os.getenv('POSTGRES_DB', 'memex_core')}")
print(f"  User: {os.getenv('POSTGRES_USER', 'memex')}")

from src.core.database import init_db, engine, Base
from src.models.archive import ArchiveRecord
from src.models.chat import ChatMessage
from src.models.session import ChatSession
from src.models.ai_config import AIModel
from src.models.prompt_config import PromptConfig  # Fix: Import PromptConfig to create table
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """重新初始化数据库表结构"""
    logger.info("Starting database table initialization...")
    
    try:
        # 使用现有的 init_db 函数，它包含了所有必要的逻辑
        init_db()
        # 这一步会根据 Base 的子类自动建表
        Base.metadata.create_all(bind=engine)
        logger.info("✅ 数据库表结构初始化完成！")
        
        # [新增] 注入默认 Prompt 种子数据
        try:
            from sqlalchemy.orm import Session
            with Session(engine) as session:
                # 检查是否已有 Prompt
                if session.query(PromptConfig).count() == 0:
                    logger.info("🌱 正在注入默认 System Prompts...")
                    
                default_prompts = [
                    PromptConfig(
                        key="system.router_main",
                        role="system",
                        group="system",
                        content="""# 角色
你是 Memex 的意图法官 (Intent Judge)。你的唯一职责是分析用户的输入，判断其意图。

# 详细配置
请参考 PROMPTS_DEFAULT.md 获取完整配置。""",
                        version=1,
                        is_active=True,
                        description="默认路由提示词 (请参考文档配置完整版)"
                    ),
                    PromptConfig(
                        key="system.chat_default",
                        role="chat",
                        group="system",
                        content="""你是由 Memex 驱动的智能助手。
详细配置请在系统初始化后，参考 PROMPTS_DEFAULT.md 手动更新。""",
                        version=1,
                        is_active=True,
                        description="默认对话提示词 (请参考文档配置完整版)"
                    )
                ]
                    
                    session.add_all(default_prompts)
                    session.commit()
                    logger.info("✅ 默认 Prompts 注入完成")
                else:
                    logger.info("ℹ️ Prompts 表已有数据，跳过种子注入")
                    
        except Exception as e:
            logger.error(f"❌ 注入默认 Prompts 失败: {e}")

        logger.info("Created tables:")
        logger.info("  - archives (Archive table)")
        logger.info("  - ai_models (AI Model Config table)")
        logger.info("  - chat_sessions (Chat Session table)")
        logger.info("  - chat_messages (Chat Message table)")
        
        logger.info("")
        logger.info("NOTE: All data has been cleared, please reconfigure:")
        logger.info("  1. Add Router model in config page")
        logger.info("  2. Add Reasoning model in config page")
        logger.info("  3. Add Vision/Audio/Memory models if needed")
        logger.info("  4. Re-upload files if needed")
        
    except Exception as e:
        logger.error(f"Initialization failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

