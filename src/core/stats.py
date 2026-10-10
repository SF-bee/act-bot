"""统计：内存累加 + 定时落库（单条消息绝不写库，保证低延迟）。

口径（群 + 日期 + 指标；``group_id = ""`` 为全局）：
    messages / commands / auto_replies / joins / leaves / active_users(当日人数快照)
    online_seconds / errors（全局）

三条自我约束：
1. **不存消息正文**；
2. **不落库「每人发了多少条」**——当天 Top N 只在内存里留着给管理员看，重启即清空；
3. **读路径必须合并内存与库**：今天的数字 = 内存增量 + 当日已落库。

第 3 条是修 bug 加的：旧实现里 ``summary()`` 只读内存 pending，而 ``flush()`` 每
``[stats].flush_seconds`` 秒就把 pending 清空，于是 /统计 的「今日消息」每隔一分钟
就归零重爬。现在统一走 :func:`daily_series`：先读库、再叠加今天的内存增量。

活跃人数（active_users）是**当日去重人数**，语义上只增不减，所以落库用 ``max``：
旧实现直接覆盖，重启后内存集合清空，一次小值 flush 就能把当天人数改小。
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date as _date
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

# 累加型指标（落库时 +）与快照型指标（落库时取 max）
SNAPSHOT_METRICS = (METRIC_ACTIVE_USERS,)
GLOBAL_GROUP = ""

DEFAULT_TZ = "Asia/Shanghai"

# 逐日序列/汇总用到的指标（同时也是 DailyStat 的字段名）
_SERIES_FIELDS = (
    METRIC_MESSAGES,
    METRIC_COMMANDS,
    METRIC_AUTO_REPLIES,
    METRIC_JOINS,
    METRIC_LEAVES,
    METRIC_ACTIVE_USERS,
)

_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"
_SPARK_EMPTY = "·"


@dataclass
class _Bucket:
    """某群某天的内存桶。"""

    pending: Counter = field(default_factory=Counter)  # 待落库的增量
    users: set[str] = field(default_factory=set)  # 当天活跃用户（去重）
    user_counts: Counter = field(default_factory=Counter)  # 仅内存：当天发言次数


@dataclass(frozen=True)
class DailyStat:
    """某群某天的一行统计（字段名与指标名一致，便于批量构造）。"""

    date: str
    messages: int = 0
    commands: int = 0
    auto_replies: int = 0
    joins: int = 0
    leaves: int = 0
    active_users: int = 0


@dataclass(frozen=True)
class DateRange:
    """一个已解析的时间区间（``dates`` 新 → 旧）。"""

    label: str
    dates: tuple[str, ...]

    @property
    def days(self) -> int:
        return len(self.dates)

    @property
    def single_day(self) -> bool:
        return len(self.dates) == 1


@dataclass(frozen=True)
class DigestEntry:
    """日报里的一行（一个群）。"""

    group_id: str
    group_name: str
    stat: DailyStat


@dataclass(frozen=True)
class DailyDigest:
    """每日活跃简报（某天的各群数据）。"""

    date: str
    entries: tuple[DigestEntry, ...] = ()


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


def recent_dates(days: int, *, tz_name: str = DEFAULT_TZ, anchor: str | None = None) -> list[str]:
    """以 ``anchor``（默认今天）为终点，往前取 ``days`` 天的日期串，新 → 旧。"""
    base = _date.fromisoformat(anchor) if anchor else datetime.now(_tz(tz_name)).date()
    return [
        (base - timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(0, max(1, int(days)))
    ]


_RANGE_RE = re.compile(r"^(?:近|最近|last)?\s*(\d+)\s*(?:天|日|d|days?)?$")
_RANGE_TODAY = ("", "今天", "今日", "today")
_RANGE_YESTERDAY = ("昨天", "昨日", "yesterday")
_RANGE_THIS_WEEK = ("本周", "这周", "本星期", "week", "this week")
_RANGE_LAST_WEEK = ("上周", "上星期", "last week")
_RANGE_THIS_MONTH = ("本月", "这个月", "month", "this month")


def parse_range(
    argument: str,
    *,
    tz_name: str = DEFAULT_TZ,
    max_days: int = 90,
) -> DateRange | None:
    """解析 /统计 的时间参数；无法识别返回 None（调用方给出用法提示）。

    支持：留空/今天/昨天/本周/上周/本月/近 N 天（近 7 天、7 天、last 7 days 都行）。
    "近 N 天"会被 ``max_days`` 截断，避免一次拉太多天。
    """
    text = (argument or "").strip().lower()
    now = datetime.now(_tz(tz_name))
    day = now.date()
    limit = max(1, int(max_days))

    def back(count: int) -> tuple[str, ...]:
        count = min(max(1, count), limit)
        return tuple((day - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(count))

    if text in _RANGE_TODAY:
        return DateRange("今天", back(1))
    if text in _RANGE_YESTERDAY:
        yesterday = (day - timedelta(days=1)).strftime("%Y-%m-%d")
        return DateRange("昨天", (yesterday,))
    if text in _RANGE_THIS_WEEK:
        span = day.weekday() + 1  # 周一 = 0
        return DateRange("本周", back(span))
    if text in _RANGE_LAST_WEEK:
        # 上周一 → 上周日
        start = day - timedelta(days=day.weekday() + 7)
        dates = tuple((start + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(7))
        return DateRange("上周", tuple(reversed(dates)))
    if text in _RANGE_THIS_MONTH:
        return DateRange("本月", back(day.day))

    match = _RANGE_RE.match(text)
    if match:
        wanted = int(match.group(1))
        if wanted < 1:
            return None
        count = min(wanted, limit)
        return DateRange("近 {0} 天".format(count), back(count))
    return None


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


def sparkline(values: Sequence[int]) -> str:
    """把数字序列画成迷你走势（``▁▂▃▄▅▆▇█``，0 用 ``·`` 表示）。纯函数。"""
    numbers = [max(0, int(value)) for value in values]
    if not numbers:
        return ""
    top = max(numbers)
    if top <= 0:
        return _SPARK_EMPTY * len(numbers)
    last = len(_SPARK_BLOCKS) - 1
    return "".join(
        _SPARK_EMPTY if value <= 0 else _SPARK_BLOCKS[min(last, int(value / top * last + 0.5))]
        for value in numbers
    )


def top_users(group_id: str, *, limit: int = 5, tz_name: str = DEFAULT_TZ) -> list[tuple[str, int]]:
    """今天发言最多的前 N 人（仅内存；重启即清空）。"""
    bucket = _buckets.get((str(group_id), today(tz_name)))
    if bucket is None:
        return []
    return bucket.user_counts.most_common(max(1, int(limit)))


def pending_errors() -> int:
    """尚未落库的错误计数（与库里的今日值相加才是总数）。"""
    return int(_errors)


def _merge_memory(group_id: str, table: dict[str, dict[str, int]], *, tz_name: str) -> None:
    """把今天尚未落库的内存增量叠加到 ``table``（就地修改）。"""
    current = today(tz_name)
    bucket = _buckets.get((group_id, current))
    if bucket is None:
        return
    slot = table.setdefault(current, {})
    for metric, value in bucket.pending.items():
        slot[metric] = int(slot.get(metric, 0)) + int(value)
    slot[METRIC_ACTIVE_USERS] = max(int(slot.get(METRIC_ACTIVE_USERS, 0)), len(bucket.users))


async def daily_series(
    group_id: str,
    dates: Sequence[str],
    *,
    tz_name: str = DEFAULT_TZ,
) -> list[DailyStat]:
    """按给定日期取逐日统计（**已合并今天的内存增量**），顺序与 ``dates`` 一致。

    这是读路径的唯一入口：库里没有的当天数字，从内存补齐。
    """
    gid = str(group_id)
    wanted = list(dict.fromkeys(str(item) for item in dates))
    if not wanted:
        return []
    async with db.get_session() as session:
        rows = (
            await session.execute(
                select(StatsDaily).where(
                    StatsDaily.group_id == gid,
                    StatsDaily.date.in_(wanted),
                    StatsDaily.metric.in_(_SERIES_FIELDS),
                )
            )
        ).scalars().all()
    table: dict[str, dict[str, int]] = {}
    for row in rows:
        table.setdefault(str(row.date), {})[str(row.metric)] = int(row.value)
    _merge_memory(gid, table, tz_name=tz_name)
    return [
        DailyStat(date=item, **{name: int(table.get(item, {}).get(name, 0)) for name in _SERIES_FIELDS})
        for item in wanted
    ]


def summarize(days: Sequence[DailyStat]) -> dict[str, int]:
    """把一个区间的逐日数据汇总成总量 + 均值（纯函数）。"""
    items = list(days)
    count = len(items)
    data = {
        METRIC_MESSAGES: sum(item.messages for item in items),
        METRIC_COMMANDS: sum(item.commands for item in items),
        METRIC_AUTO_REPLIES: sum(item.auto_replies for item in items),
        METRIC_JOINS: sum(item.joins for item in items),
        METRIC_LEAVES: sum(item.leaves for item in items),
        # 活跃人数是"当日去重人数"，跨天不能相加，这里给区间最高值，均值另给
        METRIC_ACTIVE_USERS: max((item.active_users for item in items), default=0),
        "days": count,
        "message_avg": round(sum(item.messages for item in items) / count) if count else 0,
        "active_avg": round(sum(item.active_users for item in items) / count) if count else 0,
    }
    return data


async def errors_total(
    dates: Sequence[str],
    *,
    tz_name: str = DEFAULT_TZ,
    include_pending: bool = True,
) -> int:
    """区间内的全局错误数（含尚未落库的部分，若今天在区间内）。"""
    wanted = [str(item) for item in dates]
    if not wanted:
        return 0
    async with db.get_session() as session:
        rows = (
            await session.execute(
                select(StatsDaily).where(
                    StatsDaily.group_id == GLOBAL_GROUP,
                    StatsDaily.date.in_(wanted),
                    StatsDaily.metric == METRIC_ERRORS,
                )
            )
        ).scalars().all()
    total = sum(int(row.value) for row in rows)
    if include_pending and today(tz_name) in wanted:
        total += pending_errors()
    return total


async def flush(*, tz_name: str = DEFAULT_TZ) -> int:
    """把内存增量写进 ``stats_daily``（累加型 +，快照型取 max）。返回写入行数。"""
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
                # 当日去重人数只增不减：max 避免重启后内存集合变小把数值改小
                row.value = max(int(row.value), value)
            else:
                row.value = int(row.value) + value
        await session.commit()
    written = len(additions) + len(snapshots)
    logger.debug("统计落库：%d 行", written)
    return written


async def metric_today(metric: str, group_id: str = GLOBAL_GROUP, *, tz_name: str = DEFAULT_TZ) -> int:
    """读今天该指标**已落库**的值（不含内存增量；要合并请用 daily_series）。"""
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



async def daily_digest(*, tz_name: str = DEFAULT_TZ, date: str | None = None) -> DailyDigest:
    """收集某天（默认昨天）各群的活跃数据，供日报渲染/推送。

    群列表直接来自 ``stats_daily``：有数据=那天统计是开着的，不用另外维护群名单。
    """
    target = str(date) if date else recent_dates(2, tz_name=tz_name)[-1]
    async with db.get_session() as session:
        group_ids = (
            await session.execute(
                select(StatsDaily.group_id)
                .where(StatsDaily.date == target, StatsDaily.group_id != GLOBAL_GROUP)
                .distinct()
            )
        ).scalars().all()

    from src.core import groups  # 局部导入：避免与 groups 模块的导入顺序纠缠

    entries: list[DigestEntry] = []
    for group_id in group_ids:
        series = await daily_series(group_id, [target], tz_name=tz_name)
        stat = series[0] if series else DailyStat(date=target)
        name = ""
        row = await groups.get_group(group_id)
        if row is not None and row.name:
            name = str(row.name)
        entries.append(DigestEntry(group_id=str(group_id), group_name=name, stat=stat))
    entries.sort(key=lambda item: item.stat.messages, reverse=True)
    return DailyDigest(date=target, entries=tuple(entries))


def render_digest(digest: DailyDigest, *, bot_name: str, bot_title: str) -> str:
    """渲染每日简报；没有任何群数据时返回空串（调用方据此跳过发送）。"""
    if not digest.entries:
        return ""
    lines = ["{0}（{1}）· {2} 群活跃简报".format(bot_name, bot_title, digest.date)]
    for entry in digest.entries:
        label = entry.group_name or entry.group_id
        lines.append(
            "· {0}：消息 {1:,}｜活跃 {2} 人｜入群 {3}｜退群 {4}".format(
                label,
                entry.stat.messages,
                entry.stat.active_users,
                entry.stat.joins,
                entry.stat.leaves,
            )
        )
    return "\n".join(lines)


def format_stats(
    data: dict[str, int],
    *,
    bot_name: str,
    bot_title: str,
    uptime_text: str,
    range_label: str = "今天",
    series: Sequence[DailyStat] | None = None,
    is_admin: bool = False,
    top: list[tuple[str, int]] | None = None,
    errors: int = 0,
) -> str:
    """渲染 /统计 文本（纯函数，便于测试）。

    ``data`` 是所选区间的汇总（:func:`summarize``），``series`` 是走势用的逐日数据。
    """
    days = list(series or [])
    lines = ["{0}（{1}）· 本群统计（{2}）".format(bot_name, bot_title, range_label)]
    if data.get("days", 1) > 1:
        lines.append(
            "· 消息 {0:,} 条｜日均 {1:,} 条".format(
                data.get(METRIC_MESSAGES, 0), data.get("message_avg", 0)
            )
        )
        lines.append(
            "· 活跃 {0} 人（日均 {1} 人）".format(
                data.get(METRIC_ACTIVE_USERS, 0), data.get("active_avg", 0)
            )
        )
    else:
        lines.append(
            "· 消息 {0:,} 条｜活跃 {1} 人".format(
                data.get(METRIC_MESSAGES, 0), data.get(METRIC_ACTIVE_USERS, 0)
            )
        )
    lines.append("· 入群 {0}｜退群 {1}".format(data.get(METRIC_JOINS, 0), data.get(METRIC_LEAVES, 0)))
    lines.append("· 机器人已在线 {0}".format(uptime_text))

    if days and any(item.messages for item in days):
        ordered = list(reversed(days))  # 旧 → 新，走势才读得顺
        lines.append(
            "· 近 {0} 日：{1}".format(len(ordered), sparkline([item.messages for item in ordered]))
        )
        peak = max(ordered, key=lambda item: item.messages)
        lines.append("· 峰值 {0}（{1:,} 条）".format(peak.date, peak.messages))

    if is_admin:
        lines.append(
            "· 命令 {0:,} 次｜自动回复 {1:,} 条｜错误 {2} 次".format(
                data.get(METRIC_COMMANDS, 0), data.get(METRIC_AUTO_REPLIES, 0), errors
            )
        )
        if top:
            lines.append(
                "· 今日活跃 Top{0}：{1}".format(
                    len(top), "、".join("{0}({1})".format(mask_qq(qq), count) for qq, count in top)
                )
            )
    return "\n".join(lines)
