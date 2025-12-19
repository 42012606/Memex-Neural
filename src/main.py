import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from src.core.database import init_db, SessionLocal
from src.core.logger import setup_global_logging
from src.core.error_translator import translate_ai_error
from src.api.endpoints import router as api_router
from src.models.storage import StorageRoot
from src.core.config import settings

# 1. 初始化全局日志
logger = setup_global_logging()

# 2. 生命周期管理器 (启动时初始化DB)
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Memex V3.1 Pro Backend Starting...")
    
    scheduler = None
    try:
        # [New] Scheduler for Cron Jobs
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        from src.core.config_manager import config_manager
        from src.services.nightly_jobs import run_nightly_jobs
    
        scheduler = AsyncIOScheduler()
        
        # Load Nightly Config
        nightly_cfg = config_manager.get_config("nightly")
        # Fix: key in schema is 'execution_time', not 'cron_schedule'
        cron_str = nightly_cfg.get("execution_time", "0 2 * * *") # Default 2:00 AM
        is_enable = nightly_cfg.get("enable", True)
        
        if is_enable:
            scheduler.add_job(
                run_nightly_jobs, 
                CronTrigger.from_crontab(cron_str), 
                id="nightly_jobs",
                replace_existing=True
            )
            logger.info(f"⏰ Nightly jobs scheduled: {cron_str}")
        else:
            logger.info("⏸️ Nightly jobs disabled in config.")
            
        scheduler.start()
        logger.info("⏳ Scheduler started.")
        
    except Exception as se:
        logger.error(f"❌ Scheduler init failed: {se}", exc_info=True)

    try:
        init_db()
        logger.info("✅ Database connected & schema initialized.")
        
        # [New] Run Migrations
        try:
            from src.core.migration_manager import migration_manager
            migration_manager.run_migrations()
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            # Decide if we strictly stop or continue. For now continue but log error.
            
        # [New] Config Persistence (Seeding)
        try:
            from src.core.config_manager import config_manager
            # We need a new session for seeding
            seed_db = SessionLocal()
            config_manager.initialize_defaults(seed_db)
            seed_db.close()
            logger.info("⚙️  Default Configurations Verified.")
        except Exception as e:
            logger.warning(f"⚠️ Config seeding warning: {e}")

        # [New] Prompt Manager Init
        try:
            from src.core.prompt_manager import prompt_manager
            pm_db = SessionLocal()
            prompt_manager.initialize_defaults(pm_db)
            pm_db.close()
            logger.info("🧠 Prompt Manager Initialized.")
        except Exception as e:
            logger.error(f"❌ Prompt manager init failed: {e}")

        # [New] Config Persistence (Seeding) - Original logic for AI Models and Storage Roots
        db = SessionLocal()
        try:
            # 2. AI Models
            from src.core.model_manager import model_manager
            model_manager.initialize_defaults(db)
            
            # 4. Storage Roots (Existing Logic)
            has_storage = db.query(StorageRoot).count()
            if has_storage == 0:
                default_root = StorageRoot(
                    name="Default_Local",
                    mount_path=settings.FILE_STORAGE_BASE_PATH,
                    is_active=True,
                    is_default=True,
                )
                db.add(default_root)
                db.commit()
                logger.info(f"✅ 创建默认存储卷: {default_root.name} -> {default_root.mount_path}")
            else:
                logger.info("✅ 存储卷已存在，跳过创建默认卷")

        except Exception as e:
            logger.error(f"❌ Initialization (Seeding) failed: {e}")
        finally:
            db.close()
        
        # [新增] 创建默认用户
        try:
            import sys
            from pathlib import Path
            # 添加项目根目录到 Python 路径
            project_root = Path(__file__).parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            from scripts.create_default_user import create_default_user
            create_default_user()
        except Exception as e:
            logger.warning(f"⚠️ 创建默认用户失败: {e}")

        # [新增] 初始化插件系统
        try:
            from src.core.plugins import plugin_manager
            from src.core.events import event_bus
            # [FIX] 在加载插件前清空订阅者，防止热重载时累积
            event_bus.clear_subscribers()
            plugin_manager.load_plugins()
            logger.info("🧩 Plugin System Initialized & Plugins Loaded.")
        except Exception as e:
            logger.error(f"❌ Plugin system init failed: {e}")
            
    except Exception as e:
        logger.error(f"❌ Database init failed: {e}")
    
    yield
    
    logger.info("🛑 Memex Backend Shutting down...")

# 3. 创建 App 实例
app = FastAPI(
    title="Memex API",
    version="3.1.0",
    description="Mobile-First Personal Archive System Backend",
    lifespan=lifespan
)

# 4. 配置 CORS (允许跨域，方便开发)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. 挂载静态资源（数据目录对外暴露，供音频/文件下载）
# 5. [已废弃] 静态挂载无法支持多存储根目录
# app.mount("/files", StaticFiles(directory=settings.DATA_DIR), name="files")

# [New] Dynamic File Server supporting Multiple Storage Roots
@app.get("/files/{file_path:path}")
async def serve_file(file_path: str):
    from fastapi.responses import FileResponse
    from src.models.storage import StorageRoot
    from pathlib import Path
    import os

    # 1. Try default DATA_DIR first (backward compatibility)
    default_path = Path(settings.DATA_DIR) / file_path
    if default_path.exists() and default_path.is_file():
        return FileResponse(default_path)
    
    # 2. Iterate through all active Storage Roots
    db = SessionLocal()
    try:
        roots = db.query(StorageRoot).filter(StorageRoot.is_active == True).all()
        for root in roots:
            # Construct potential full path
            # root.mount_path could be "D:/Archives"
            # file_path could be "admin/2025.12/Images/foo.jpg"
            
            # Security check: prevent ../ traversal
            safe_file_path = os.path.normpath(file_path)
            if safe_file_path.startswith("..") or os.path.isabs(safe_file_path):
                continue
                
            full_path = Path(root.mount_path) / safe_file_path
            
            if full_path.exists() and full_path.is_file():
                return FileResponse(full_path)
    finally:
        db.close()
        
    # 3. If not found in any root
    return JSONResponse(status_code=404, content={"detail": "File not found in any storage root"})

# 6. 导入所有路由
from src.api.endpoints import router as api_router
from src.api.config_endpoints import router as config_router
from src.api.data_endpoints import router as data_router
from src.api.batch_endpoints import router as batch_router
from src.api.chat import router as chat_router 
from src.api.cron_endpoints import router as cron_router # [New] Cron Router
from src.api.system_endpoints import router as system_router # [New] System Router
from src.api.audio_endpoints import router as audio_router # [New] Audio Router
from src.api.auth_endpoints import router as auth_router  # [新增] 认证路由
from src.api.user_endpoints import router as user_router  # [新增] 用户管理路由
from src.api.dashboard_endpoints import router as dashboard_router # [New] Dashboard Router
from src.api.proposal_endpoints import router as proposal_router # [New] Proposal Router
from src.api.prompts import router as prompts_router # [New] PromptOps Router
from src.api.storage_endpoints import router as storage_router # [New]


# 7. 注册所有 API 路由
app.include_router(auth_router, prefix="/api/v1", tags=["Authentication"])  # [新增] 认证路由
app.include_router(user_router, prefix="/api/v1", tags=["User Management"])  # [新增] 用户管理路由
app.include_router(api_router, prefix="/api/v1", tags=["Memex Core"])
app.include_router(chat_router, prefix="/api/v1", tags=["Chat System"])
app.include_router(config_router, prefix="/api/v1", tags=["Config Management"])
app.include_router(data_router, prefix="/api/v1", tags=["Data Management"])
app.include_router(batch_router, prefix="/api/v1", tags=["Batch Import"])
app.include_router(cron_router, prefix="/api/v1", tags=["Cron Jobs"]) # [New]
app.include_router(system_router, prefix="/api/v1", tags=["System"])
app.include_router(audio_router, prefix="/api/v1", tags=["Audio"]) # [New]
app.include_router(dashboard_router, prefix="/api/v1", tags=["Dashboard"]) # [New]
app.include_router(proposal_router, prefix="/api/v1", tags=["Proposals"]) # [New]
app.include_router(prompts_router, prefix="/api/prompts", tags=["PromptOps"]) # [New] PromptOps Endpoints
app.include_router(storage_router, prefix="/api/v1", tags=["Storage Management"]) # [New] Storage Repos

# 8. [关键] 挂载静态资源
# 这样前端 HTML 里的 <link href="/static/css/style.css"> 才能找到文件
# directory="web" 表示把容器里的 /app/web 目录映射为 /static
app.mount("/static", StaticFiles(directory="web"), name="static")

# 9. 根路径返回主页
@app.get("/")
async def read_index():
    # 返回拆分后的结构化 HTML
    return FileResponse('web/index.html')

# 9.1 Dashboard 页面
@app.get("/dashboard")
async def read_dashboard():
    return FileResponse('web/dashboard.html')

# 10. 全局异常处理器（错误信息中文化）

# 10. 全局异常处理器（错误信息中文化）
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器，将错误信息翻译为中文"""
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    error_msg = translate_ai_error(str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "detail": error_msg,
            "type": type(exc).__name__
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 异常处理器，翻译错误信息"""
    translated_detail = translate_ai_error(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": translated_detail,
            "type": "HTTPException"
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """请求验证异常处理器"""
    return JSONResponse(
        status_code=422,
        content={
            "detail": "请求参数验证失败，请检查输入格式",
            "errors": exc.errors()
        }
    )

# 9. 健康检查
@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "3.1.0"}
