import sys
import logging
import os
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from src.core.config import settings
from src.core.log_manager import log_manager

def setup_global_logging():
    """配置全局日志系统，接管所有模块的输出"""
    
    root_logger = logging.getLogger()
    
    # 防止重复配置
    if any(handler is log_manager for handler in root_logger.handlers):
        return root_logger
    
    root_logger.setLevel(logging.INFO)

    # 彻底清理所有 handlers
    for name in list(logging.Logger.manager.loggerDict.keys()):
        logger_instance = logging.getLogger(name)
        logger_instance.handlers = []
    root_logger.handlers = []

    # 定义统一格式
    formatter = logging.Formatter(
        '%(asctime)s - [%(name)s] - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 禁用 uvicorn 日志传播
    for log_name in ["uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"]:
        ul = logging.getLogger(log_name)
        ul.propagate = False
        ul.handlers = []

    # 日志目录
    log_dir = settings.LOG_PATH
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    # 内存 Handler
    log_manager.setFormatter(formatter)
    root_logger.addHandler(log_manager)

    # 屏蔽第三方库日志
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)

    return root_logger




