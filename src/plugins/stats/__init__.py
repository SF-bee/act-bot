"""stats：活跃统计（内存累加 + 定时落库）。

- 订阅 `MessageReceived` / `GroupMemberJoin` / `GroupMemberLeave`（feature=stats）；
- `/stats`：成员看本群今天的活跃概览；管理员额外看到命令数、自动回复数、错误数与今日活跃 Top N；
- 开关走 `/config stats on|off`（遵守命令分层约定：本插件不提供开关命令）；
- 自动回复数由 welcome / chat 在发送成功后调用 `stats.record_auto_reply` 记入；
- 错误数由事件入口在中枢报告失败时记入。

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
    description="活跃统计（消息 / 活跃人数 / 命令 / 自动回复 / 入群退群 / 在线时长 / 错误）",
    usage="/stats — 查看本群活跃统计（管理员可见更详细数据）",
    extra={"role": "member", "order": 40},
)

stats_cmd = on_command("stats", priority=10, block=True)


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


@stats_cmd.handle()
async def _handle_stats(event: MessageEvent) -> None:
    if not isinstance(event, GroupMessageEvent):
        await stats_cmd.finish("这个命令要在群里用。")
    settings = get_settings()
    tz_name = settings.timezone
    group_id = str(event.group_id)
    is_admin = await perms.is_admin(str(event.user_id))

    data = dict(stats.summary(group_id, tz_name=tz_name))
    top: list[tuple[str, int]] = []
    history: dict[str, int] | None = None
    if is_admin:
        data[stats.METRIC_ERRORS] = stats.pending_errors() + await stats.metric_today(
            stats.METRIC_ERRORS, tz_name=tz_name
        )
        top = stats.top_users(group_id, limit=settings.stats_top_users, tz_name=tz_name)
        history = await stats.history_totals(
            group_id, days=settings.stats_history_days, tz_name=tz_name
        )

    text = stats.format_stats(
        data,
        bot_name=persona.name(),
        bot_title=persona.title(),
        uptime_text=stats.format_duration(stats.uptime_seconds()),
        is_admin=is_admin,
        top=top,
        history=history,
        history_days=settings.stats_history_days,
    )
    await stats_cmd.finish(text)

