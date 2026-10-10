"""消息推送封装：定时任务等「后台流程要主动发消息」的场景走这里。

为什么单独一层：
- 主动发送和「收到消息再回复」不同——没有 event，得自己从 nonebot 拿已连接的 Bot；
- 「挑账号 + 逐个 try/except + 日志」每次推送都一样，集中在这里，调度器只写
  「什么时候发 + 发什么」（见 src/core/scheduler.py）。

约定：
- 默认只用一个 Bot（部署通常只有一个账号；用多个会让管理员收到重复消息）；
- 单个目标失败不影响其它目标，返回成功条数；
- 没有任何已连接 Bot 时安全返回 0，只记日志（后台任务不该因为没人上线而炸）。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Sequence
from typing import Any

logger = logging.getLogger("actbot.notify")


def _bots() -> list[Any]:
    """当前已连接的 Bot 列表（单独成函数，便于测试替换）。"""
    try:
        import nonebot

        return list(nonebot.get_bots().values())
    except Exception:  # noqa: BLE001 - 未初始化 / 无 nonebot 时当作没有
        return []


def _pick(explicit: Sequence[Any] | None) -> Any | None:
    """选一个发送账号；没有可用账号返回 None。"""
    bots = list(explicit) if explicit is not None else _bots()
    if not bots:
        logger.warning("没有已连接的协议端，消息未发送")
        return None
    if len(bots) > 1:
        logger.warning("检测到 %d 个已连接账号，本次只用第一个发送", len(bots))
    return bots[0]


def _unique(items: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items))


async def send_private(
    qqs: Iterable[Any],
    text: str,
    *,
    bots: Sequence[Any] | None = None,
) -> int:
    """私聊发送给若干 QQ；返回成功条数。"""
    bot = _pick(bots)
    if bot is None:
        return 0
    sent = 0
    for qq in _unique(qqs):
        try:
            await bot.send_private_msg(user_id=int(qq), message=text)
            sent += 1
        except Exception:  # noqa: BLE001 - 单个失败不影响其它人
            logger.warning("私聊发送失败：qq=%s", qq, exc_info=True)
    return sent


async def send_group(
    group_ids: Iterable[Any],
    text: str,
    *,
    bots: Sequence[Any] | None = None,
    interval_seconds: float = 0.0,
) -> int:
    """群发到若干群；interval_seconds 是群与群之间的间隔（降风控）。返回成功条数。"""
    bot = _pick(bots)
    if bot is None:
        return 0
    sent = 0
    for index, group_id in enumerate(_unique(group_ids)):
        if index and interval_seconds > 0:
            await asyncio.sleep(float(interval_seconds))
        try:
            await bot.send_group_msg(group_id=int(group_id), message=text)
            sent += 1
        except Exception:  # noqa: BLE001 - 单个失败不影响其它群
            logger.warning("群消息发送失败：group=%s", group_id, exc_info=True)
    return sent


async def notify_admins(text: str, *, bots: Sequence[Any] | None = None) -> int:
    """私聊全部管理员；返回成功条数。"""
    from src.core import permissions as perms

    admins = await perms.list_admins()
    return await send_private([item.qq for item in admins], text, bots=bots)
