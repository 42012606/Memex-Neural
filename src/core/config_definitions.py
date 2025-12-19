"""
[AI_GUIDE_V1]
CRITICAL ARCHITECTURE NOTE:
This file implements a SCHEMA-DRIVEN configuration system.
- DO NOT refactor the core classes (ConfigField, ConfigGroup) unless strictly necessary.
- TO ADD NEW SETTINGS: simply append a new `ConfigGroup` or add a `ConfigField` to an existing group in the `get_all_definitions()` list.
- This file acts as a PLUGIN REGISTRY. The Frontend UI generates itself automatically based on this list.
- NO frontend code changes are required when adding new settings here.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class ConfigField(BaseModel):
    """
    Defines a single configuration field (Input, Toggle, Select, etc.)
    """
    key: str = Field(..., description="Dot-notation key, e.g., 'system.webhook_url'")
    label: str = Field(..., description="Human readable label for UI")
    type: str = Field(..., description="UI Component type: 'string', 'number', 'boolean', 'select', 'password', 'path', 'textarea'")
    default: Any = Field(..., description="Default value")
    description: Optional[str] = Field(None, description="Helper text shown below input")
    options: Optional[List[Dict[str, str]]] = Field(None, description="For 'select' type: [{'label': 'A', 'value': 'a'}]")
    is_secret: bool = Field(False, description="If True, value is masked in UI and logs")
    required: bool = Field(False)

class ConfigGroup(BaseModel):
    """
    Defines a logical group of settings (renders as a Panel or Tab in UI)
    """
    id: str
    title: str
    description: Optional[str] = None
    icon: Optional[str] = Field("settings", description="Material Icon name")
    fields: List[ConfigField]


def get_all_definitions() -> List[ConfigGroup]:
    """
    PLUGIN REGISTRY
    Add new Configuration Groups here.
    """
    return [
        # --- Group 1: System Basic ---
        ConfigGroup(
            id="system",
            title="基础设置",
            description="System-level configurations",
            icon="tune",
            fields=[
                ConfigField(
                    key="system.debug_mode", 
                    label="调试模式 (Debug Mode)", 
                    type="boolean", 
                    default=False, 
                    description="启用详细的日志输出，用于排查问题。"
                ),
                ConfigField(
                    key="system.max_concurrency", 
                    label="最大并发任务数", 
                    type="number", 
                    default=5, 
                    description="限制后台同时运行的任务数量（如OCR、分析等），防止系统过载。"
                ),
            ]
        ),



        # --- Group 3: Nightly Jobs ---
        ConfigGroup(
            id="nightly",
            title="夜间任务",
            description="自动化维护与早报生成",
            icon="bedtime",
            fields=[
                ConfigField(
                    key="nightly.enable", 
                    label="启用夜间任务", 
                    type="boolean", 
                    default=True
                ),
                ConfigField(
                    key="nightly.auto_refine", 
                    label="自动语义切分 (Auto Refine)", 
                    type="boolean", 
                    default=False,
                    description="如果启用，将自动接受高置信度的语义切分建议，无需人工确认。"
                ),
                ConfigField(
                    key="nightly.morning_briefing", 
                    label="启用每日早报 (Morning Briefing)", 
                    type="boolean", 
                    default=True,
                    description="每天生成一份系统活动与新归档内容的摘要报告。"
                ),
                ConfigField(
                    key="nightly.execution_time", 
                    label="执行时间 (Cron String)", 
                    type="string", 
                    default="0 2 * * *", 
                    description="设置任务执行的 Cron 表达式 (默认: 每天凌晨 2:00)。"
                ),
            ]
        ),

        # --- Group 4: Notifications (Webhooks) ---
        ConfigGroup(
            id="notifications",
            title="通知与集成",
            description="通过 Webhook 集成外部通知",
            icon="notifications_active",
            fields=[
                ConfigField(
                    key="notifications.enable", 
                    label="启用通知", 
                    type="boolean", 
                    default=False
                ),
                ConfigField(
                    key="notifications.webhook_url", 
                    label="Webhook URL", 
                    type="string", 
                    default="", 
                    description="接收系统事件通知的目标 URL (支持 Slack/钉钉/飞书)。",
                    is_secret=True
                ),
                ConfigField(
                    key="notifications.events", 
                    label="触发事件", 
                    type="select", 
                    default="all",
                    options=[
                        {"label": "所有事件 (All)", "value": "all"},
                        {"label": "仅错误 (Errors Only)", "value": "error"},
                        {"label": "任务完成 (Task Complete)", "value": "task_done"},
                    ]
                )
            ]
        ),

        # --- Group 5: Router Tuning ---
        ConfigGroup(
            id="router_tuning",
            title="路由调优",
            description="微调 AI 路由行为",
            icon="psychology",
            fields=[
                # ConfigField for router.strategy removed (Force Intervention)
                ConfigField(
                    key="router.search_threshold", 
                    label="搜索置信度阈值", 
                    type="number", 
                    default=0.6,
                    description="当 AI 判断需要搜索的置信度超过此值时，自动触发向量搜索。"
                ),
                # ConfigField for router.allow_ambiguity removed (Allow Vague Follow-up)
            ]
        ),

        # Batch Operations Group removed
    ]

