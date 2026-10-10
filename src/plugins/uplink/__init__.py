"""uplink：协议端掉线提醒。

腾讯吊销登录态时协议端会发一条 `notice.bot_offline`（"你的账号当前登录已失效"）。
这一刻账号已经不在线、私聊发不出去，所以这里**只记时间**；等协议端重新连上
（`driver.on_bot_connect`）再私聊管理员补一条汇总（掉了多久 / 在线了多久）。

开关：`config/config.toml` 的 `[alert] uplink`（默认开）。逻辑在 `src/core/uplink.py`，
本插件只做「接事件 → 调 core」。
"""
from __future__ import annotations

import logging

import nonebot
from nonebot import on_notice
from nonebot.adapters.onebot.v11 import NoticeEvent
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from src.core import notify, uplink
from src.core.config import get_settings

logger = logging.getLogger("actbot.uplink")

__plugin_meta__ = PluginMetadata(
    name="uplink",
    description="协议端掉线提醒（被踢下线后，重新上线时私聊管理员汇总）",
    usage="",  # 无用户命令：不进帮助菜单（/帮助 跳过 usage 为空的插件）
    extra={"role": "admin", "order": 80},
)


def _is_bot_offline(event: NoticeEvent) -> bool:
    return event.notice_type == "bot_offline"


# 优先级 1（比事件中枢的 99 高）：先记掉线，再让它照常分发；block=False 不拦事件
bot_offline = on_notice(rule=Rule(_is_bot_offline), priority=1, block=False)


@bot_offline.handle()
async def _handle_bot_offline(event: NoticeEvent) -> None:
    detail = str(getattr(event, "message", "") or "").strip()
    outage = uplink.mark_offline(event.self_id, detail=detail)
    logger.warning(
        "协议端掉线：%s", uplink.render_offline(outage, tz_name=get_settings().timezone)
    )


@nonebot.get_driver().on_bot_connect
async def _on_bot_connect(bot) -> None:
    settings = get_settings()
    recovery = uplink.mark_online(bot.self_id)
    if recovery is None:  # 进程启动后的首次上线（或协议端自身重启），不需要提醒
        return
    logger.warning(
        "协议端已恢复：%s",
        uplink.render_offline(recovery.outage, tz_name=settings.timezone),
    )
    if not settings.alert_uplink:
        return
    text = uplink.render_recovery(
        recovery,
        bot_name=settings.persona_name,
        bot_title=settings.persona_title,
        tz_name=settings.timezone,
    )
    await notify.notify_admins(text)
