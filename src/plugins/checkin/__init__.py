"""checkin：群互动 · 签到打卡（/签到、/签到榜）。

- 两层开关：全局 [features].checkin（默认关，先在 config.toml 打开）+ 群级 /config checkin on|off；
- 文案模板与榜单参数在 config.toml 的 [checkin] 段（占位符见 docs/checkin.md）；
- 逻辑与渲染都在 src/core/checkin.py，本文件只负责命令注册、开关判定与异常兜底。
"""
from __future__ import annotations

import logging
from typing import Any

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.plugin import PluginMetadata

from src.core import checkin, features, groups, persona
from src.core.config import AppSettings, get_settings
from src.core.onebot import safe_group_name, safe_member_label

logger = logging.getLogger("actbot.checkin")

__plugin_meta__ = PluginMetadata(
    name="checkin",
    description="群互动 · 签到打卡与签到榜",
    usage=(
        "/签到 — 打卡（别名 /checkin、/打卡）\n"
        "/签到榜 [本月|累计] — 本群签到排行（别名 /checkin_rank、/签到排行）"
    ),
    extra={"role": "member", "order": 45},
)

checkin_cmd = on_command("签到", aliases={"checkin", "打卡"}, priority=10, block=True)
rank_cmd = on_command("签到榜", aliases={"checkin_rank", "签到排行"}, priority=10, block=True)

_USAGE = "用法：/签到榜 [本月|累计]（默认本月）"

# /签到 后面写这些词，等价于 /签到榜（习惯写法兜底）
_RANK_WORDS = ("榜", "排行", "榜单", "排名")


def _argument(event: MessageEvent) -> str:
    """取命令后的第一个参数（/签到榜 累计 → 累计）。"""
    parts = event.message.extract_plain_text().split()
    return parts[1] if len(parts) > 1 else ""


async def _gate(event: MessageEvent, matcher: Any) -> tuple[AppSettings, GroupMessageEvent] | None:
    """公共前置：群聊限定 + 全局开关 + 群级开关。

    不通过时已回复并返回 None（全局关闭时安静不响应，遵守命令分层约定）。
    """
    if not isinstance(event, GroupMessageEvent):
        await matcher.finish("这个命令要在群里用～")
    settings = get_settings()
    if not settings.feature(features.FEATURE_CHECKIN):
        return None
    enabled = await groups.feature_enabled(
        str(event.group_id),
        features.FEATURE_CHECKIN,
        default=features.default_of(features.FEATURE_CHECKIN),
    )
    if not enabled:
        await matcher.finish("本群还没有开启签到，让管理员发 /config checkin on 试试～")
    return settings, event


async def _leaderboard_text(
    bot: Bot, group: GroupMessageEvent, settings: AppSettings, argument: str
) -> str:
    """榜单文本；参数不合法 / 查询失败 / 空榜都返回可直接发送的提示语。"""
    group_id = str(group.group_id)
    try:
        scope = checkin.parse_scope(argument or settings.checkin_rank_scope)
    except ValueError:
        return _USAGE
    try:
        rows = await checkin.leaderboard(
            group_id,
            scope=scope,
            limit=settings.checkin_rank_size,
            tz_name=settings.timezone,
        )
    except Exception:  # noqa: BLE001 - 命令层兜底，不让异常冒到事件中枢
        logger.exception("签到榜查询失败：group=%s", group_id)
        return "签到榜查询失败了，稍后再试试～"
    if not rows:
        return "本群还没有人签到过，发 /签到 抢个第一名？"
    return checkin.render_leaderboard(
        rows,
        scope=scope,
        group_name=await safe_group_name(bot, group_id),
        bot_name=persona.name(),
        bot_title=persona.title(),
    )


@checkin_cmd.handle()
async def _handle_checkin(bot: Bot, event: MessageEvent) -> None:
    gate = await _gate(event, checkin_cmd)
    if gate is None:
        return
    settings, group = gate
    group_id = str(group.group_id)
    if _argument(event) in _RANK_WORDS:  # /签到 榜 之类
        await checkin_cmd.finish(await _leaderboard_text(bot, group, settings, ""))
    nickname = await safe_member_label(bot, group_id, str(group.user_id))
    try:
        result = await checkin.check_in(
            group_id,
            str(group.user_id),
            display_name=nickname,
            tz_name=settings.timezone,
        )
    except Exception:  # noqa: BLE001 - 命令层兜底
        logger.exception("签到失败：group=%s user=%s", group_id, group.user_id)
        await checkin_cmd.finish("签到失败了，稍后再试试～")
    text = checkin.render_checkin(
        result,
        nickname=nickname,
        group_name=await safe_group_name(bot, group_id),
        bot_name=persona.name(),
        bot_title=persona.title(),
        settings=settings,
    )
    await checkin_cmd.finish(text)


@rank_cmd.handle()
async def _handle_rank(bot: Bot, event: MessageEvent) -> None:
    gate = await _gate(event, rank_cmd)
    if gate is None:
        return
    settings, group = gate
    await rank_cmd.finish(await _leaderboard_text(bot, group, settings, _argument(event)))
