"""统计：内存累加 + 定时落库（单条消息绝不写库，保证低延迟）。

口径（群 + 日期 + 指标；``group_id = ""`` 为全局）：
    messages / commands / auto_replies / joins / leaves / active_users(当日人数快照)
    online_seconds / errors（全局）

两条自我约束：
1. **不存消息正文**；
2. **不落库「每人发了多少条」**——当天 Top N 只在内存里留着给管理员看，重启即清空。

今天的数字读内存（实时），历史读 ``stats_daily`` 表。
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.core import db
from src.core.config import get_settings
from src.models.tables import StatsDaily

logger = logging.getLogger("actbot.stats")

METRIC_MESSAGES = "messages"
METRIC_COMMANDS = "commands"
METRIC_AUTO_REPLIES = "auto_replies"
METRIC_JOINS = "joins"
METRIC_LEAVES = "leaves"
METRIC_ACTIVE_USERS = "active_users"
METRIC_ONLINE_SECONDS = "online_seconds"
METRIC_ERRORS = "errors"

# 累加型指标（落库时 +）与快照型指标（落库时 =）
SNAPSHOT_METRICS = (METRIC_ACTIVE_USERS,)
GLOBAL_GROUP = ""

DEFAULT_TZ = "Asia/Shanghai"


@dataclass
class _Bucket:
    """某群某天的内存桶。"""

    pending: Counter = field(default_factory=Counter)  # 待落库的增量
    users: set[str] = field(default_factory=set)  # 当天活跃用户（去重）
    user_counts: Counter = field(default_factory=Counter)  # 仅内存：当天发言次数


_buckets: dict[tuple[str, str], _Bucket] = {}
_started_at = time.monotonic()
_last_flush_at = time.monotonic()
_errors = 0


def _tz(tz_name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 - 时区数据缺失时退回 UTC，不让统计崩
        return timezone.utc


def today(tz_name: str = DEFAULT_TZ) -> str:
    """本地时区的日期串（YYYY-MM-DD）。"""
    return datetime.now(_tz(tz_name)).strftime("%Y-%m-%d")


def recent_dates(days: int, *, tz_name: str = DEFAULT_TZ) -> list[str]:
    """最近 ``days`` 天（含今天）的日期串，新 → 旧。"""
    anchor = datetime.now(_tz(tz_name)).date()
    return [(anchor - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(0, max(1, int(days)))]


def command_name(text: str, prefixes: tuple[str, ...] = ("/",)) -> str | None:
    """从消息文本取命令名（不含前缀）；不是命令返回 None。"""
    stripped = (text or "").strip()
    for prefix in prefixes:
        if prefix and stripped.startswith(prefix):
            rest = stripped[len(prefix):].strip()
            return rest.split()[0] if rest else ""
    return None


def mask_qq(qq: str) -> str:
    """QQ 号打码（保留前 3 后 2），用于在群里展示活跃榜。"""
    text = str(qq)
    if len(text) <= 5:
        return "***"
    return text[:3] + "*" * (len(text) - 5) + text[-2:]


def reset_state() -> None:
    """清空内存状态（测试用）。"""
    global _errors, _last_flush_at
    _buckets.clear()
    _errors = 0
    _last_flush_at = time.monotonic()


def _enabled() -> bool:
    return bool(get_settings().feature("stats"))


def _bucket(group_id: str, date: str) -> _Bucket:
    key = (str(group_id), str(date))
    bucket = _buckets.get(key)
    if bucket is None:
        bucket = _Bucket()
        _buckets[key] = bucket
    return bucket


def record_message(
    group_id: str,
    user_id: str,
    text: str,
    *,
    prefixes: tuple[str, ...] = ("/",),
    tz_name: str = DEFAULT_TZ,
) -> None:
    """记一条消息（含是否命令）、刷新当天活跃用户。"""
    if not _enabled():
        return
    bucket = _bucket(group_id, today(tz_name))
    bucket.pending[METRIC_MESSAGES] += 1
    user = str(user_id)
    bucket.users.add(user)
    bucket.user_counts[user] += 1
    if command_name(text, prefixes) is not None:
        bucket.pending[METRIC_COMMANDS] += 1


def record_join(group_id: str, *, tz_name: str = DEFAULT_TZ) -> None:
    if _enabled():
        _bucket(group_id, today(tz_name)).pending[METRIC_JOINS] += 1


def record_leave(group_id: str, *, tz_name: str = DEFAULT_TZ) -> None:
    if _enabled():
        _bucket(group_id, today(tz_name)).pending[METRIC_LEAVES] += 1


def record_auto_reply(group_id: str, *, tz_name: str = DEFAULT_TZ) -> None:
    """记一次机器人的自动回复（欢迎 / 聊天）。"""
    if _enabled():
        _bucket(group_id, today(tz_name)).pending[METRIC_AUTO_REPLIES] += 1


def record_error() -> None:
    """记一次消费者异常（全局）。"""
    global _errors
    if _enabled():
        _errors += 1


def uptime_seconds() -> float:
    """本进程已运行秒数。"""
    return time.monotonic() - _started_at


def format_duration(seconds: float) -> str:
    """秒 → 人类可读（``3 小时 12 分`` / ``5 分 20 秒``）。"""
    total = int(max(0.0, seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return "{0} 小时 {1} 分".format(hours, minutes)
    if minutes:
        return "{0} 分 {1} 秒".format(minutes, secs)
    return "{0} 秒".format(secs)


def summary(group_id: str, *, tz_name: str = DEFAULT_TZ) -> dict[str, int]:
    """本群今天的实时数字（内存）。"""
    bucket = _buckets.get((str(group_id), today(tz_name)))
    if bucket is None:
        return {}
    data = {metric: int(value) for metric, value in bucket.pending.items()}
    data[METRIC_ACTIVE_USERS] = len(bucket.users)
    return data


def pending_errors() -> int:
    """尚未落库的错误计数（与库里的今日值相加才是总数）。"""
    return int(_errors)


def top_users(group_id: str, *, limit: int = 5, tz_name: str = DEFAULT_TZ) -> list[tuple[str, int]]:
    """今天发言最多的前 N 人（仅内存；重启即清空）。"""
    bucket = _buckets.get((str(group_id), today(tz_name)))
    if bucket is None:
        return []
    return bucket.user_counts.most_common(max(1, int(limit)))


async def flush(*, tz_name: str = DEFAULT_TZ) -> int:
    """把内存增量写进 ``stats_daily``（累加型 + 快照型分别处理）。返回写入行数。"""
    global _last_flush_at, _errors
    if not _enabled():
        return 0
    moment = time.monotonic()
    online_delta = int(max(0.0, moment - _last_flush_at))
    _last_flush_at = moment

    additions: list[tuple[str, str, str, int]] = []
    snapshots: list[tuple[str, str, str, int]] = []
    for (group_id, date), bucket in list(_buckets.items()):
        for metric, value in bucket.pending.items():
            if value:
                additions.append((group_id, date, metric, int(value)))
        bucket.pending.clear()
        if bucket.users:
            snapshots.append((group_id, date, METRIC_ACTIVE_USERS, len(bucket.users)))
    if online_delta:
        additions.append((GLOBAL_GROUP, today(tz_name), METRIC_ONLINE_SECONDS, online_delta))
    if _errors:
        additions.append((GLOBAL_GROUP, today(tz_name), METRIC_ERRORS, int(_errors)))
        _errors = 0
    if not additions and not snapshots:
        return 0

    async with db.get_session() as session:
        for group_id, date, metric, value in additions + snapshots:
            row = (
                await session.execute(
                    select(StatsDaily).where(
                        StatsDaily.group_id == group_id,
                        StatsDaily.date == date,
                        StatsDaily.metric == metric,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(StatsDaily(group_id=group_id, date=date, metric=metric, value=value))
            elif metric in SNAPSHOT_METRICS:
                row.value = value
            else:
                row.value = int(row.value) + value
        await session.commit()
    written = len(additions) + len(snapshots)
    logger.debug("统计落库：%d 行", written)
    return written


async def metric_today(metric: str, group_id: str = GLOBAL_GROUP, *, tz_name: str = DEFAULT_TZ) -> int:
    """读今天该指标已落库的值（内存里的增量不含在内）。"""
    async with db.get_session() as session:
        row = (
            await session.execute(
                select(StatsDaily).where(
                    StatsDaily.group_id == str(group_id),
                    StatsDaily.date == today(tz_name),
                    StatsDaily.metric == metric,
                )
            )
        ).scalar_one_or_none()
    return int(row.value) if row is not None else 0


async def history_totals(
    group_id: str, *, days: int = 7, tz_name: str = DEFAULT_TZ
) -> dict[str, int]:
    """最近 ``days`` 天（不含今天）的汇总：消息 / 入群 / 退群。"""
    dates = set(recent_dates(days, tz_name=tz_name)) - {today(tz_name)}
    wanted = (METRIC_MESSAGES, METRIC_JOINS, METRIC_LEAVES)
    async with db.get_session() as session:
        rows = (
            await session.execute(
                select(StatsDaily).where(
                    StatsDaily.group_id == str(group_id),
                    StatsDaily.metric.in_(wanted),
                )
            )
        ).scalars().all()
    totals = {metric: 0 for metric in wanted}
    for row in rows:
        if row.date in dates:
            totals[row.metric] = totals.get(row.metric, 0) + int(row.value)
    return totals


def format_stats(
    data: dict[str, int],
    *,
    bot_name: str,
    bot_title: str,
    uptime_text: str,
    is_admin: bool = False,
    top: list[tuple[str, int]] | None = None,
    history: dict[str, int] | None = None,
    history_days: int = 7,
) -> str:
    """渲染 /stats 文本（纯函数，便于测试）。"""
    lines = ["{0}（{1}）· 本群统计（今天）".format(bot_name, bot_title)]
    lines.append(
        "· 消息 {0} 条｜活跃 {1} 人".format(
            data.get(METRIC_MESSAGES, 0), data.get(METRIC_ACTIVE_USERS, 0)
        )
    )
    lines.append("· 入群 {0}｜退群 {1}".format(data.get(METRIC_JOINS, 0), data.get(METRIC_LEAVES, 0)))
    lines.append("· 已在线 {0}".format(uptime_text))
    if is_admin:
        lines.append(
            "· 命令 {0} 次｜自动回复 {1} 条｜错误 {2} 次".format(
                data.get(METRIC_COMMANDS, 0),
                data.get(METRIC_AUTO_REPLIES, 0),
                data.get(METRIC_ERRORS, 0),
            )
        )
        if top:
            lines.append(
                "· 今日活跃 Top{0}：{1}".format(
                    len(top), "、".join("{0}({1})".format(mask_qq(qq), count) for qq, count in top)
                )
            )
        if history:
            lines.append(
                "· 近 {0} 天：消息 {1}｜入群 {2}｜退群 {3}".format(
                    history_days,
                    history.get(METRIC_MESSAGES, 0),
                    history.get(METRIC_JOINS, 0),
                    history.get(METRIC_LEAVES, 0),
                )
            )
    return "\n".join(lines)

