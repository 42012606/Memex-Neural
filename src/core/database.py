import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from src.core.config import settings

# 配置日志
logger = logging.getLogger(__name__)

# 1. 创建数据库引擎 (Engine)
# 使用 settings 里的 DATABASE_URL (支持 Postgres 或 SQLite)
# echo=False 关闭 SQL 语句刷屏，避免日志太乱
try:
    engine = create_engine(
        settings.DATABASE_URL, 
        echo=False,
        # 如果是 SQLite，需要 check_same_thread=False
        connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    )
    logger.info("✅ 数据库引擎已加载")
except Exception as e:
    logger.error(f"❌ 数据库连接失败: {e}")
    raise e

# 2. 创建会话工厂 (SessionLocal)
# 也就是我们用来操作数据库的"手"
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 3. [关键修复] 定义 ORM 基类 (Base)
# 所有的 Model (如 ArchiveRecord) 都要继承它，报错就是因为缺了这个
Base = declarative_base()

# 4. 依赖注入函数 (get_db)
# 给 Web 端和 Processor 用的，用完自动关闭连接
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 5. 初始化数据库表结构的辅助函数
def init_db():
    """在应用启动时调用，确保表存在"""
    logger.info("🛠️ 正在初始化数据库表结构...")
    
    # [Critical Fix] 确保 pgvector 扩展已启用
    # 必须在创建表之前执行，否则 VECTOR 类型会报错
    try:
        with engine.begin() as conn:
            from sqlalchemy import text
            # 开启 vector 扩展
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            logger.info("✅ 已启用 pgvector 扩展")
    except Exception as e:
        logger.error(f"❌ 启用 pgvector 扩展失败: {e}")
        # Note: if this fails, subsequent table creation involving VECTOR will likely fail too

    
    # 导入所有模型，确保表结构被注册
    from src.models.archive import ArchiveRecord
    from src.core.config_manager import SystemConfig
    from src.models.chat import ChatMessage
    from src.models.session import ChatSession
    from src.models.ai_config import AIModel  # [新增] 注册 AIModel
    from src.models.user import User  # [新增] 注册 User 模型
    from src.models.storage import StorageRoot  # [新增] 存储卷模型
    from src.models.proposal import Proposal # [New] Register Proposal
    from src.models.vector_node import VectorNode # [New] Register VectorNode
    from src.models.prompt_config import PromptConfig # [New] Register PromptConfig for PromptOps
    
    # [紧急修复] 检查并修复 chat_sessions 表的结构问题
    # 处理 UUID id 和 user_id 缺失的情况
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(engine)
        
        if inspector.has_table("chat_sessions"):
            columns = [col['name'] for col in inspector.get_columns("chat_sessions")]
            logger.info(f"📊 chat_sessions 当前列: {columns}")
            
            # 检查 user_id 是否存在
            if 'user_id' not in columns:
                logger.warning("⚠️ chat_sessions 缺少 user_id 列，正在添加...")
                # 使用 begin() 确保事务正确提交
                with engine.begin() as conn:
                    # 对于 PostgreSQL，如果表中有数据，需要先添加列（允许NULL），然后更新，最后设置NOT NULL
                    # 但这里使用 DEFAULT 1，所以可以直接添加
                    try:
                        conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN user_id INTEGER DEFAULT 1 NOT NULL"))
                        logger.info("✅ 成功添加 user_id 列")
                    except Exception as alter_error:
                        # 如果失败（可能因为表中有数据且列已存在但类型不同），尝试另一种方式
                        logger.warning(f"⚠️ 直接添加列失败: {alter_error}，尝试分步添加...")
                        try:
                            # 先添加允许NULL的列
                            conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN user_id INTEGER"))
                            # 更新现有记录
                            conn.execute(text("UPDATE chat_sessions SET user_id = 1 WHERE user_id IS NULL"))
                            # 设置NOT NULL约束
                            conn.execute(text("ALTER TABLE chat_sessions ALTER COLUMN user_id SET NOT NULL"))
                            conn.execute(text("ALTER TABLE chat_sessions ALTER COLUMN user_id SET DEFAULT 1"))
                            logger.info("✅ 成功分步添加 user_id 列")
                        except Exception as fallback_error:
                            logger.error(f"❌ 分步添加列也失败: {fallback_error}")
                            raise
            
            # 检查 id 列类型 (如果是 integer 需要迁移，但这很复杂，暂时只打日志)
            id_col = next((c for c in inspector.get_columns("chat_sessions") if c['name'] == 'id'), None)
            if id_col:
                id_type_str = str(id_col.get('type', '')).upper()
                if 'INTEGER' in id_type_str or 'INT' in id_type_str:
                    logger.warning("⚠️ chat_sessions.id 仍为 INTEGER 类型，建议清空表以应用 UUID 更改")
                    logger.warning("   如需迁移，请手动备份数据后删除表，让系统重新创建")
                elif 'VARCHAR' in id_type_str or 'TEXT' in id_type_str or 'CHAR' in id_type_str:
                    logger.info("✅ chat_sessions.id 已是字符串类型（UUID）")
        
        # [修复] 检查并修复 ai_models 表的结构
        if inspector.has_table("ai_models"):
            columns = [col['name'] for col in inspector.get_columns("ai_models")]
            logger.info(f"📊 ai_models 当前列: {columns}")
            
            # 检查并添加 config 列
            if 'config' not in columns:
                logger.warning("⚠️ ai_models 缺少 config 列，正在添加...")
                with engine.begin() as conn:
                    try:
                        conn.execute(text("ALTER TABLE ai_models ADD COLUMN config JSONB"))
                        logger.info("✅ 成功添加 ai_models.config 列")
                    except Exception as e:
                        logger.error(f"❌ 添加 config 列失败: {e}")
                        logger.exception(e)
            else:
                logger.info("✅ ai_models.config 列已存在")
            
            # 检查并添加 agent_type 列
            if 'agent_type' not in columns:
                logger.warning("⚠️ ai_models 缺少 agent_type 列，正在添加...")
                with engine.begin() as conn:
                    try:
                        # 先添加列（允许NULL，因为已有数据）
                        conn.execute(text("ALTER TABLE ai_models ADD COLUMN agent_type VARCHAR(20)"))
                        # 为现有数据设置默认值（假设都是推理模型）
                        conn.execute(text("UPDATE ai_models SET agent_type = 'reasoning' WHERE agent_type IS NULL"))
                        # 设置NOT NULL约束
                        conn.execute(text("ALTER TABLE ai_models ALTER COLUMN agent_type SET NOT NULL"))
                        # 创建索引
                        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ai_models_agent_type ON ai_models(agent_type)"))
                        logger.info("✅ 成功添加 ai_models.agent_type 列")
                    except Exception as e:
                        logger.error(f"❌ 添加 agent_type 列失败: {e}")
                        logger.exception(e)
            else:
                logger.info("✅ ai_models.agent_type 列已存在")

        # [新增] archives 表结构检查：添加 storage_root_id 与 relative_path
        if inspector.has_table("archives"):
            columns = [col['name'] for col in inspector.get_columns("archives")]
            logger.info(f"📊 archives 当前列: {columns}")
            with engine.begin() as conn:
                if 'storage_root_id' not in columns:
                    try:
                        conn.execute(text("ALTER TABLE archives ADD COLUMN storage_root_id INTEGER"))
                        logger.info("✅ 已添加 archives.storage_root_id 列")
                    except Exception as e:
                        logger.warning(f"⚠️ 添加 storage_root_id 失败: {e}")
                        conn.execute(text("ALTER TABLE archives ADD COLUMN relative_path VARCHAR"))
                        logger.info("✅ 已添加 archives.relative_path 列")
                    except Exception as e:
                        logger.warning(f"⚠️ 添加 relative_path 失败: {e}")

        # [新增] prompt_configs 表结构检查：添加 role
        if inspector.has_table("prompt_configs"):
            columns = [col['name'] for col in inspector.get_columns("prompt_configs")]
            logger.info(f"📊 prompt_configs 当前列: {columns}")
            with engine.begin() as conn:
                if 'role' not in columns:
                    try:
                        conn.execute(text("ALTER TABLE prompt_configs ADD COLUMN role VARCHAR(50)"))
                        logger.info("✅ 已添加 prompt_configs.role 列")
                    except Exception as e:
                        logger.warning(f"⚠️ 添加 role 失败: {e}")
            
    except Exception as e:
        logger.error(f"❌ 检查/修复表结构时出错: {e}")
        logger.exception(e)  # 打印完整堆栈跟踪
        # 不阻止启动，但记录详细错误
    
    # 这一步会根据 Base 的子类自动建表
    Base.metadata.create_all(bind=engine)
    logger.info("✅ 数据库表结构初始化完成！")