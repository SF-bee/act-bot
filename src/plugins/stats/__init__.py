"""stats：活跃统计（内存累加 + 定时落库）。

- 订阅 MessageReceived / GroupMemberJoin / GroupMemberLeave（feature=stats）；
- /统计 [今天|昨天|本周|上周|本月|近N天]：本群活跃概览 + 逐日走势；
  管理员额外看到命令数、自动回复数、错误数与今日活跃 Top N；
- 默认时间范围是今天；数字来自「内存增量 + 当日已落库」，因此不会出现
  「每次落库就归零」的问题（历史 bug，见 src/core/stats.py 模块注释）；
- 开关走 /config stats on|off（遵守命令分层约定：本插件不提供开关命令）；
- 自动回复数由 welcome / chat 在发送成功后调用 stats.record_auto_reply 记入；
- 错误数由事件入口在中枢报告失败时记入；
- 每日简报由调度器调用 stats.daily_digest 渲染后私聊管理员（见 scheduler.py）。

隐私约束：**不存消息正文**，也**不落库「每人发了多少条」**——Top N 仅存内存，重启即清空。
"""
from __future__ import annotations

import logging

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.plugin import PluginMetadata

from src.core import persona, stats
from src.core import permissions as perms
from src.core.config import get_settings
from src.core.events import GroupMemberJoin, GroupMemberLeave, MessageReceived, subscribe
from src.core.onebot import command_prefixes

logger = logging.getLogger("actbot.stats")

__plugin_meta__ = PluginMetadata(
    name="stats",
    description="活跃统计（消息 / 活跃人数 / 命令 / 自动回复 / 入群退群 / 在线时长 / 错误 / 走势）",
    usage=(
        "/统计 [今天|昨天|本周|上周|本月|近N天] — 查看本群活跃统计（别名 /stats）\n"
        "　管理员可见更多：命令 / 自动回复 / 错误 / 今日活跃 Top N"
    ),
    extra={"role": "member", "order": 40},
)

stats_cmd = on_command("统计", aliases={"stats"}, priority=10, block=True)

_USAGE = (
    "用法：/统计 [今天|昨天|本周|上周|本月|近N天]\n"
    "例：/统计、/统计 本周、/统计 近30天"
)


@subscribe(MessageReceived, feature="stats", name="stats-message")
async def _on_message(event: MessageReceived, bot) -> None:
    if not event.is_group:
        return
    stats.record_message(
        event.group_id,
        event.user_id,
        event.text,
        prefixes=command_prefixes(),
        tz_name=get_settings().timezone,
    )


@subscribe(GroupMemberJoin, feature="stats", name="stats-join")
async def _on_join(event: GroupMemberJoin, bot) -> None:
    stats.record_join(event.group_id, tz_name=get_settings().timezone)


@subscribe(GroupMemberLeave, feature="stats", name="stats-leave")
async def _on_leave(event: GroupMemberLeave, bot) -> None:
    stats.record_leave(event.group_id, tz_name=get_settings().timezone)


def _argument(event: MessageEvent) -> str:
    """取命令后的第一个参数（/统计 本周 → 本周）。"""
    parts = event.message.extract_plain_text().split()
    return parts[1] if len(parts) > 1 else ""


@stats_cmd.handle()
async def _handle_stats(event: MessageEvent) -> None:
    if not isinstance(event, GroupMessageEvent):
        await stats_cmd.finish("这个命令要在群里用。")

    settings = get_settings()
    tz_name = settings.timezone
    group_id = str(event.group_id)
    is_admin = await perms.is_admin(str(event.user_id))

    span = stats.parse_range(
        _argument(event), tz_name=tz_name, max_days=settings.stats_range_max_days
    )
    if span is None:
        await stats_cmd.finish(_USAGE)

    range_series = await stats.daily_series(group_id, span.dates, tz_name=tz_name)
    data = stats.summarize(range_series)
    trend_dates = stats.recent_dates(
        settings.stats_trend_days, tz_name=tz_name, anchor=span.dates[0]
    )
    trend = await stats.daily_series(group_id, trend_dates, tz_name=tz_name)

    top: list[tuple[str, int]] = []
    errors = 0
    if is_admin:
        top = stats.top_users(group_id, limit=settings.stats_top_users, tz_name=tz_name)
        errors = await stats.errors_total(span.dates, tz_name=tz_name)

    text = stats.format_stats(
        data,
        bot_name=persona.name(),
        bot_title=persona.title(),
        uptime_text=stats.format_duration(stats.uptime_seconds()),
        range_label=span.label,
        series=trend,
        is_admin=is_admin,
        top=top,
        errors=errors,
    )
    await stats_cmd.finish(text)
