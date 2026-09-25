"""群级设置（groups 表）：群信息与群内功能开关。

原则：QQ 群号只来自事件或数据库，代码中不出现任何具体群号。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from src.core import db
from src.models.tables import Group


def utc_now() -> str:
    """UTC 时间字符串（ISO-8601，秒级；与 admins 表同一格式）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def get_group(group_id: str | int) -> Group | None:
    """按群号取群记录；未登记返回 None。"""
    gid = str(group_id)
    async with db.get_session() as session:
        return (
            await session.execute(select(Group).where(Group.group_id == gid))
        ).scalar_one_or_none()


async def welcome_enabled(group_id: str | int) -> bool:
    """群级入群欢迎开关；未登记的群按开启处理（全局开关另算）。"""
    row = await get_group(group_id)
    return True if row is None else bool(row.welcome_on)


async def set_welcome_enabled(group_id: str | int, enabled: bool, name: str = "") -> None:
    """设置群级入群欢迎开关；群未登记则顺带登记（可带群名）。"""
    gid = str(group_id)
    async with db.get_session() as session:
        row = (
            await session.execute(select(Group).where(Group.group_id == gid))
        ).scalar_one_or_none()
        if row is None:
            session.add(
                Group(
                    group_id=gid,
                    name=name,
                    welcome_on=1 if enabled else 0,
                    created_at=utc_now(),
                )
            )
        else:
            row.welcome_on = 1 if enabled else 0
            if name:
                row.name = name
        await session.commit()
