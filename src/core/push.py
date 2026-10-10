"""定时推送：把「什么时候发 / 发什么 / 发给谁」全部交给 config.toml，改配置即可。

配置写在 ``config/config.toml`` 的 ``[[push]]`` 数组里（示例见
``config/config.example.toml``）::

    [[push]]
    name = "早安"
    at = "08:00"               # HH:MM，或 ["08:00", "20:00"]
    weekdays = ["mon", "wed"]  # 可选；不写 = 每天
    targets = ["all"]          # "admins" / "all" / 具体群号
    text = "{bot_name}：早上好，今天是 {date}（{weekday}）～"

改动后**重启业务层**即可生效，不需要改代码。

职责边界（本模块是「一个功能」，不再让每条推送各写一段 job）：
- :mod:`src.core.notify` —— 怎么发（挑账号、逐个发、失败隔离）；
- :mod:`src.core.scheduler` —— 启动时调用 :func:`register_jobs`，把配置交给 APScheduler。

占位符：``{bot_name}`` ``{bot_title}`` ``{date}`` ``{time}`` ``{weekday}``。
用 ``str.replace`` 而不是 ``str.format``：没写的花括号原样保留，正文里含 ``{``
也不会让整条推送报错。
"""
from __future__ import annotations

import logging
import zoneinfo
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from .config import PushSchedule, WEEKDAY_NAMES, get_settings

logger = logging.getLogger("actbot.push")

TARGET_ADMINS = "admins"
TARGET_ALL = "all"

# CronTrigger 的 day_of_week 取值（0=周一，与 config.parse_weekdays 对齐）
_CRON_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _tz(name: str) -> zoneinfo.ZoneInfo | None:
    try:
        return zoneinfo.ZoneInfo(name)
    except Exception:  # noqa: BLE001 - 时区异常时退回系统本地时间
        logger.warning("时区 %r 无法解析，定时推送回退为系统本地时区", name)
        return None


def render_text(text: str, *, now: datetime, bot_name: str = "", bot_title: str = "") -> str:
    """替换推送里的占位符；未识别的花括号原样保留。"""
    values = {
        "{bot_name}": str(bot_name),
        "{bot_title}": str(bot_title),
        "{date}": now.strftime("%Y-%m-%d"),
        "{time}": now.strftime("%H:%M"),
        "{weekday}": WEEKDAY_NAMES[now.weekday()],
    }
    rendered = str(text)
    for key, value in values.items():
        rendered = rendered.replace(key, value)
    return rendered


async def _resolve_group_ids(targets: Sequence[str]) -> list[str]:
    """把 targets 解析成群号列表（"all" = 群名册里全部启用的群）。"""
    from . import groups

    group_ids: list[str] = list(await groups.group_ids()) if TARGET_ALL in targets else []
    for target in targets:
        if target in (TARGET_ADMINS, TARGET_ALL):
            continue
        if target not in group_ids:
            group_ids.append(target)
    return group_ids


async def send_push(
    schedule: PushSchedule,
    *,
    now: datetime | None = None,
    interval_seconds: float = 0.0,
    bots: Sequence[Any] | None = None,
) -> int:
    """执行一条推送；返回成功发送条数。"""
    from . import groups, notify, persona

    settings = get_settings()
    moment = now or datetime.now(_tz(settings.timezone))
    text = render_text(
        schedule.text, now=moment, bot_name=persona.name(), bot_title=persona.title()
    )

    sent = 0
    if TARGET_ADMINS in schedule.targets:
        sent += await notify.notify_admins(text, bots=bots)

    group_ids = await _resolve_group_ids(schedule.targets)
    if schedule.feature and group_ids:
        group_ids = [
            gid for gid in group_ids if await groups.feature_enabled(gid, schedule.feature)
        ]
    if group_ids:
        sent += await notify.send_group(
            group_ids, text, bots=bots, interval_seconds=interval_seconds
        )
    return sent


def _make_job(schedule: PushSchedule):
    async def _job() -> None:
        try:
            sent = await send_push(
                schedule, interval_seconds=get_settings().broadcast_interval_seconds
            )
            logger.info("定时推送「%s」已发送：%d 条", schedule.name, sent)
        except Exception:  # noqa: BLE001 - 定时任务失败不影响机器人运行
            logger.exception("定时推送「%s」失败", schedule.name)

    return _job


def register_jobs(scheduler: Any, settings: Any) -> int:
    """把配置里的 [[push]] 注册成定时任务；返回注册的 job 数。"""
    from apscheduler.triggers.cron import CronTrigger

    registered = 0
    for schedule in settings.pushes:
        if not schedule.enabled or not schedule.times:
            continue
        for index, (hour, minute) in enumerate(schedule.times):
            kwargs: dict[str, Any] = {"hour": hour, "minute": minute}
            if schedule.weekdays:
                kwargs["day_of_week"] = ",".join(_CRON_DAYS[day] for day in schedule.weekdays)
            scheduler.add_job(
                _make_job(schedule),
                CronTrigger(**kwargs),
                id=f"push:{schedule.name}:{index}",
                replace_existing=True,
            )
            registered += 1
    return registered


def all_pushes() -> tuple[PushSchedule, ...]:
    """当前配置里的全部推送（含停用的）。"""
    return get_settings().pushes


def _target_label(target: str) -> str:
    if target == TARGET_ADMINS:
        return "私聊管理员"
    if target == TARGET_ALL:
        return "全部群"
    return f"群 {target}"


def describe(schedule: PushSchedule) -> str:
    """一条推送的一行人话描述（/推送 列表、日志用）。"""
    times = (
        "、".join(f"{hour:02d}:{minute:02d}" for hour, minute in schedule.times) or "无时间"
    )
    days = (
        "每天"
        if not schedule.weekdays
        else "、".join(WEEKDAY_NAMES[day] for day in schedule.weekdays)
    )
    targets = "、".join(_target_label(item) for item in schedule.targets) or "无目标"
    state = "启用" if schedule.enabled else "停用"
    line = f"「{schedule.name}」{times} · {days} · {targets} · {state}"
    if schedule.feature:
        line += f"（仅 {schedule.feature} 开启的群）"
    return line
