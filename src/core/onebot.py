"""OneBot API 的容错封装：调用失败时返回兜底值，不让业务逻辑因小错中断。

为什么单独放一层：取昵称/群名属于"锦上添花"的信息，拿不到也不该让欢迎、
审计等功能整体失败；集中在这里也避免各插件各写一份 try/except。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("actbot.onebot")


async def safe_group_name(bot: Any, group_id: str) -> str:
    """群名；取不到返回空串。"""
    try:
        info = await bot.get_group_info(group_id=int(group_id))
        return str(info.get("group_name") or "")
    except Exception:  # noqa: BLE001 - 拿不到就退回空串
        logger.debug("获取群信息失败：group=%s", group_id)
        return ""


async def safe_member_label(bot: Any, group_id: str, user_id: str) -> str:
    """成员在群里的显示名（群名片优先）；取不到退回 QQ 号。"""
    try:
        info = await bot.get_group_member_info(
            group_id=int(group_id), user_id=int(user_id), no_cache=True
        )
        return str(info.get("card") or info.get("nickname") or user_id)
    except Exception:  # noqa: BLE001 - 拿不到就用 QQ 号
        logger.debug("获取群成员信息失败：group=%s user=%s", group_id, user_id)
        return user_id

