"""events：事件中枢的唯一入口。

把 OneBot 原始事件交给 src.core.events 规范化并分发。
消费者**不要**直接挂 OneBot 事件，用 `subscribe(...)` 声明订阅，
这样群级开关（feature）、cooldown、异常隔离都由中枢统一负责。
"""
from __future__ import annotations

from nonebot import on_message, on_notice
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, NoticeEvent
from nonebot.plugin import PluginMetadata

from src.core import events

__plugin_meta__ = PluginMetadata(
    name="events",
    description="事件中枢（规范化 + 群级门控 + 分发）",
    usage="",  # 无用户命令：不进帮助菜单（/help 跳过 usage 为空的插件）
    extra={"role": "member", "order": 5},
)

# 优先级 99 = 最低：先让命令类 matcher（优先级 10）处理完，中枢只观察不拦截
message_ingress = on_message(priority=99, block=False)
notice_ingress = on_notice(priority=99, block=False)


@message_ingress.handle()
async def _ingest_message(bot: Bot, event: MessageEvent) -> None:
    await events.ingest(event, bot)


@notice_ingress.handle()
async def _ingest_notice(bot: Bot, event: NoticeEvent) -> None:
    await events.ingest(event, bot)

