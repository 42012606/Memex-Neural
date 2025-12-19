# src/core/config.py
import os
from pathlib import Path
from typing import Dict, List
from pydantic import BaseModel

class Settings(BaseModel):
    # --- 基础路径 ---
    DATA_DIR: str = os.getenv("DATA_DIR", "/app/data")
    FILE_STORAGE_BASE_PATH: str = os.getenv("FILE_STORAGE_BASE_PATH", "/app/data")
    
    # [预留扩展] 多用户支持：当前单用户模式，user_id 固定为 1
    # TODO: 未来多用户时，user_id 将从 Session/JWT 中获取
    USER_ID: int = int(os.getenv("USER_ID", "1"))
    
    @property
    def USER_DATA_DIR(self) -> Path:
        """用户数据目录"""
        # [单用户模式] 统一指向 admin 目录，不再使用 users/1
        return Path(self.DATA_DIR) / "admin"
    
    @property
    def INBOX_PATH(self) -> Path:
        # [预留扩展] 改为使用用户数据目录
        return self.USER_DATA_DIR / "_INBOX"
    
    @property
    def REVIEW_PATH(self) -> Path:
        # [预留扩展] 改为使用用户数据目录
        return self.USER_DATA_DIR / "_NEEDS_REVIEW"
    
    @property
    def LOG_PATH(self) -> Path:
        # 统一日志目录到 data/logs (不再分散到 users/x/)
        return Path(self.DATA_DIR) / "logs"
    
    # [新增] 文件类型到扩展名映射（添加类型注解）
    FILE_TYPE_MAPPING: Dict[str, List[str]] = {
        "Documents": [".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"],
        "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"],
        "Audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"],
        "Video": [".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm"],
        "Memos": [".memo", ".note"]  # 对话总结等
    }
    
    # [预留] 家庭影音目录（未来模块使用）
    FAMILY_MEDIA_PATH: str = os.getenv("FAMILY_MEDIA_PATH", "")
    
    # --- 数据库配置 ---
    DB_USER: str = os.getenv("POSTGRES_USER", "memex")
    DB_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")
    DB_HOST: str = os.getenv("POSTGRES_HOST", "db")
    DB_PORT: str = os.getenv("POSTGRES_PORT", "5432")
    DB_NAME: str = os.getenv("POSTGRES_DB", "memex_core")

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    # --- AI 配置 ---
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "GEMINI")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
    
    # --- 文件服务配置 ---
    # 用于 DashScope API 访问本地文件的域名/URL
    # 例如: https://yourdomain.com 或 http://yourdomain.com:5000
    FILE_SERVICE_BASE_URL: str = os.getenv("FILE_SERVICE_BASE_URL", "http://localhost:19527")

# 单例模式：全局只实例化一次
settings = Settings()

# 自动创建必要目录
for p in [settings.INBOX_PATH, settings.REVIEW_PATH, settings.LOG_PATH]:
    p.mkdir(parents=True, exist_ok=True)