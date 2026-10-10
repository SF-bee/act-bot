"""群级设置（groups 表）：群信息与各功能的群内开关。

开关统一存在 ``groups.features``（JSON 文本）里，例如
``{"welcome": true, "chat": false}``；未登记的开关按传入的 ``default`` 处理（默认开启）。

原则：QQ 群号只来自事件或数据库，代码中不出现任何具体群号。
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select

from src.core import db
from src.core.db import utc_now
from src.models.tables import Group

logger = logging.getLogger("actbot.groups")

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


async def list_groups(*, active_only: bool = True) -> list[Group]:
    """全部已登记的群（默认只含 active=1）；按群号升序。"""
    async with db.get_session() as session:
        query = select(Group)
        if active_only:
            query = query.where(Group.active == 1)
        rows = (await session.execute(query.order_by(Group.group_id))).scalars().all()
        return list(rows)


async def group_ids(*, active_only: bool = True) -> list[str]:
    """已登记群的群号列表（用于群发/遍历）。"""
    return [str(row.group_id) for row in await list_groups(active_only=active_only)]


async def upsert_group(group_id: str | int, name: str = "", *, active: bool = True) -> None:
    """登记 / 更新一个群；已登记群的 features 保持不变。"""
    gid = str(group_id)
    async with db.get_session() as session:
        row = (
            await session.execute(select(Group).where(Group.group_id == gid))
        ).scalar_one_or_none()
        if row is None:
            session.add(
                Group(
                    group_id=gid,
                    name=name or "",
                    active=1 if active else 0,
                    created_at=utc_now(),
                )
            )
        else:
            if name and row.name != name:
                row.name = name
            row.active = 1 if active else 0
        await session.commit()


async def sync_groups(entries) -> int:
    """按协议端返回的群列表登记群名册；返回登记的群数。"""
    count = 0
    for entry in entries or []:
        gid = str(entry.get("group_id", "")).strip()
        if not gid:
            continue
        await upsert_group(gid, str(entry.get("group_name", "") or ""))
        count += 1
    return count


async def sync_from_bot(bot) -> int:
    """机器人连上协议端时同步群列表；失败只记日志，返回 0。"""
    try:
        entries = await bot.get_group_list()
    except Exception:  # noqa: BLE001 - 同步失败不影响机器人运行
        logger.warning("获取群列表失败，群名册跳过本次同步", exc_info=True)
        return 0
    return await sync_groups(entries)


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

