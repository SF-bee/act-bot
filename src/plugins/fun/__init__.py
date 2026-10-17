"""fun：群互动 · 骰子 / 今日运势 / 随机选择。

- 两层开关：全局 ``[features].fun``（默认开）+ 群级 ``/config fun on|off``；
- 文案与随机逻辑在 ``src/core/fun.py``，本文件只做命令注册、门控与异常兜底；
- 不落库、不调用外部服务。
"""
from __future__ import annotations

import logging
from typing import Any

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from src.core import features, fun, groups, stats
from src.core.config import AppSettings, get_settings
from src.core.onebot import safe_member_label

logger = logging.getLogger("actbot.fun")

__plugin_meta__ = PluginMetadata(
    name="fun",
    description="群互动 · 骰子、今日运势、随机选择",
    usage=(
        "/骰子 [NdM] — 掷骰子（默认 1d6；例：/骰子 2d6；别名 /roll、/dice）\n"
        "/运势 — 今日运势（别名 /fortune、/今日运势）\n"
        "/选一个 <选项...> — 从 2–20 个选项里随机选一个（别名 /choose、/select）"
    ),
    extra={"role": "member", "order": 40},
)

dice_cmd = on_command("骰子", aliases={"roll", "dice"}, priority=10, block=True)
fortune_cmd = on_command("运势", aliases={"fortune", "今日运势"}, priority=10, block=True)
choose_cmd = on_command("选一个", aliases={"choose", "select"}, priority=10, block=True)


async def _gate(event: MessageEvent, matcher: Any) -> AppSettings | None:
    """群聊限定 + 全局开关 + 群级开关；不通过时已回复并返回 None。"""
    if not isinstance(event, GroupMessageEvent):
        await matcher.finish("这个命令要在群里玩才有意思嘛～")
    settings = get_settings()
    if not settings.feature(features.FEATURE_FUN):
        return None  # 全局关闭：安静不响应
    enabled = await groups.feature_enabled(
        str(event.group_id),
        features.FEATURE_FUN,
        default=features.default_of(features.FEATURE_FUN),
    )
    if not enabled:
        await matcher.finish("本群还没开启群互动，喊管理员发 /config fun on，一起玩起来～")
    return settings


@dice_cmd.handle()
async def _handle_dice(event: MessageEvent, arg: Message = CommandArg()) -> None:
    if await _gate(event, dice_cmd) is None:
        return
    spec = arg.extract_plain_text().strip() or "1d6"
    try:
        result = fun.roll_dice(spec)
    except ValueError as exc:
        await dice_cmd.finish(str(exc))
    await dice_cmd.finish(fun.render_dice(result))


@fortune_cmd.handle()
async def _handle_fortune(bot: Bot, event: MessageEvent) -> None:
    settings = await _gate(event, fortune_cmd)
    if settings is None:
        return
    group_id = str(event.group_id)
    nickname = await safe_member_label(bot, group_id, str(event.user_id))
    date = stats.today(settings.timezone)
    try:
        result = fun.fortune(
            str(event.user_id), date=date, texts=settings.fun_fortune_texts
        )
    except ValueError:
        logger.warning("运势文案未配置，跳过 /运势")
        await fortune_cmd.finish("运势签还没准备好，请管理员检查一下 [fun].fortune_texts～")
    await fortune_cmd.finish(fun.render_fortune(result, nickname=nickname, date=date))


@choose_cmd.handle()
async def _handle_choose(event: MessageEvent, arg: Message = CommandArg()) -> None:
    if await _gate(event, choose_cmd) is None:
        return
    options = fun.parse_options(arg.extract_plain_text())
    try:
        chosen = fun.choose(options)
    except ValueError as exc:
        await choose_cmd.finish(str(exc))
    await choose_cmd.finish(f"🎯 叮！从 {len(options)} 个选项里抽中：{chosen}～")
