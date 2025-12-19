import logging
from fastapi import APIRouter

from src.api.cron import (
    run_daily_summary,
    run_memory_distillation,
    run_nightly_jobs,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/cron/daily-summary")
async def trigger_daily_summary():
    """手动触发每日 Summary"""
    logger.info("⏳ Manual trigger: daily summary")
    return await run_daily_summary()


@router.post("/cron/distill")
async def trigger_memory_distillation():
    """手动触发偏好蒸馏"""
    logger.info("⏳ Manual trigger: memory distillation")
    return await run_memory_distillation()


@router.post("/cron/nightly")
async def trigger_nightly_jobs():
    """串行执行 Summary + Distillation"""
    logger.info("⏳ Manual trigger: nightly jobs")
    return await run_nightly_jobs()
