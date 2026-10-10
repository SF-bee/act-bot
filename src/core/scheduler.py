"""定时任务（APScheduler）：跨平台，不依赖系统 cron / 计划任务。

目前注册四类任务：
- 每日备份（backup.daily_at）；
- 统计落库（每 stats.flush_seconds 秒，把内存增量写库）；
- 每日群活跃简报（stats.digest_at，私聊管理员，不打扰群成员）；
- 定时推送（config.toml 的 [[push]]，由 :mod:`src.core.push` 解析并注册，
  改配置即可增删，不需要改代码）。
"""
from __future__ import annotations

import logging
import zoneinfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import backup, push
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

    if settings.feature("stats"):
        async def _flush_stats() -> None:
            """把统计内存增量落库（避免每条消息写库）。"""
            try:
                from src.core import stats

                await stats.flush(tz_name=settings.timezone)
            except Exception:  # noqa: BLE001 - 落库失败不影响机器人运行
                logger.exception("统计落库失败")

        scheduler.add_job(
            _flush_stats,
            IntervalTrigger(seconds=float(settings.stats_flush_seconds)),
            id="stats-flush",
            replace_existing=True,
        )

        if settings.stats_digest_at:
            digest_hour, digest_minute = parse_hhmm(settings.stats_digest_at)

            async def _daily_stats_digest() -> None:
                """把昨天的群活跃简报私聊给管理员（只在私聊，不打扰群成员）。"""
                try:
                    from src.core import notify, persona, stats

                    digest = await stats.daily_digest(tz_name=settings.timezone)
                    text = stats.render_digest(
                        digest, bot_name=persona.name(), bot_title=persona.title()
                    )
                    if not text:
                        logger.info("统计日报：%s 没有群数据，跳过", digest.date)
                        return
                    sent = await notify.notify_admins(text)
                    logger.info("统计日报已发送：%d 条私聊（%s）", sent, digest.date)
                except Exception:  # noqa: BLE001 - 日报失败不影响机器人运行
                    logger.exception("统计日报发送失败")

            scheduler.add_job(
                _daily_stats_digest,
                CronTrigger(hour=digest_hour, minute=digest_minute),
                id="stats-digest",
                replace_existing=True,
            )
    registered = push.register_jobs(scheduler, settings)
    if registered:
        logger.info("已注册 %d 个定时推送（config.toml 的 [[push]]）", registered)

    scheduler.start()
    _scheduler = scheduler
    logger.info("调度器已启动：每日备份 %02d:%02d（%s）", hour, minute, settings.timezone)


def shutdown() -> None:
    """停止调度器（bot 退出时调用）。"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
