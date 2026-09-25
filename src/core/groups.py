"""群级设置（groups 表）：群信息与各功能的群内开关。

开关统一存在 ``groups.features``（JSON 文本）里，例如
``{"welcome": true, "chat": false}``；未登记的开关按传入的 ``default`` 处理（默认开启）。

原则：QQ 群号只来自事件或数据库，代码中不出现任何具体群号。
"""
from __future__ import annotations

import json

from sqlalchemy import select

from src.core import db
from src.core.db import utc_now
from src.models.tables import Group

FEATURE_WELCOME = "welcome"


def _loads(raw: str | None) -> dict[str, bool]:
    """容错解析 features JSON；坏数据当空字典处理。"""
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): bool(value) for key, value in data.items()}


async def get_group(group_id: str | int) -> Group | None:
    """按群号取群记录；未登记返回 None。"""
    gid = str(group_id)
    async with db.get_session() as session:
        return (
            await session.execute(select(Group).where(Group.group_id == gid))
        ).scalar_one_or_none()


async def feature_enabled(group_id: str | int, feature: str, *, default: bool = True) -> bool:
    """群级开关查询：未登记的群 / 未登记的开关都返回 ``default``。"""
    row = await get_group(group_id)
    if row is None:
        return default
    return _loads(row.features).get(str(feature), default)


async def set_feature(
    group_id: str | int,
    feature: str,
    enabled: bool,
    *,
    group_name: str = "",
) -> None:
    """设置群级开关；群未登记则顺带登记（可带群名）。"""
    gid = str(group_id)
    async with db.get_session() as session:
        row = (
            await session.execute(select(Group).where(Group.group_id == gid))
        ).scalar_one_or_none()
        if row is None:
            row = Group(group_id=gid, name=group_name, created_at=utc_now())
            session.add(row)
        elif group_name and row.name != group_name:
            row.name = group_name
        features = _loads(row.features)
        features[str(feature)] = bool(enabled)
        row.features = json.dumps(features, ensure_ascii=False, sort_keys=True)
        await session.commit()


async def welcome_enabled(group_id: str | int) -> bool:
    """群级入群欢迎开关（全局开关另算）。"""
    return await feature_enabled(group_id, FEATURE_WELCOME)


async def set_welcome_enabled(group_id: str | int, enabled: bool, name: str = "") -> None:
    """设置群级入群欢迎开关。"""
    await set_feature(group_id, FEATURE_WELCOME, enabled, group_name=name)


def parse_feature_command(text: str) -> tuple[str, str]:
    """解析 ``/config <feature> on|off``：返回 (feature, action)。

    action 取值：``""``（只看状态）、``on``、``off``、``unknown``（参数非法）。
    """
    parts = text.strip().split()
    if len(parts) < 2:
        return "", ""
    feature = parts[1].strip().lower()
    if len(parts) < 3:
        return feature, ""
    action = parts[2].strip().lower()
    if action not in ("on", "off"):
        return feature, "unknown"
    return feature, action

