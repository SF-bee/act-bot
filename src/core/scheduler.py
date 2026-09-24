"""定时任务（APScheduler）：跨平台，不依赖系统 cron / 计划任务。

P0 只注册"每日备份"；后续功能（社活提醒等）在此扩展。
"""
from __future__ import annotations

import logging
import zoneinfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import backup
from .config import get_settings, parse_hhmm

logger = logging.getLogger("actbot.scheduler")

_scheduler: AsyncIOScheduler | None = None


def _resolve_timezone(name: str) -> zoneinfo.ZoneInfo | None:
    try:
        return zoneinfo.ZoneInfo(name)
    except Exception:
        logger.warning("时区 %r 无法解析，调度器回退为系统本地时区", name)
        return None


def setup_and_start() -> None:
    """注册并启动调度器（容错：配置异常时只告警，不阻断 bot 启动）。"""
    global _scheduler
    if _scheduler is not None:
        return
    settings = get_settings()
    try:
        hour, minute = parse_hhmm(settings.backup_daily_at)
    except Exception as exc:
        logger.warning("每日备份时间配置无效（%s），已跳过备份调度", exc)
        return

    scheduler = AsyncIOScheduler(timezone=_resolve_timezone(settings.timezone))

    def _daily_backup() -> None:
        try:
            path = backup.backup_database(
                keep_daily_days=settings.backup_keep_daily_days,
                keep_monthly=settings.backup_keep_monthly,
            )
            logger.info("每日备份完成：%s", path)
        except Exception:
            logger.exception("每日备份失败")

    scheduler.add_job(
        _daily_backup,
        CronTrigger(hour=hour, minute=minute),
        id="daily-backup",
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("调度器已启动：每日备份 %02d:%02d（%s）", hour, minute, settings.timezone)


def shutdown() -> None:
    """停止调度器（bot 退出时调用）。"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
