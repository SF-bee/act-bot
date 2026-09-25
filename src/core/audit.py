"""审计日志：谁 / 何时 / 在哪个群 / 做了什么管理操作。

表结构见迁移 001 + 002（audit_log: qq, action, detail, group_id, created_at）。
写库是唯一职责；展示格式由 :func:`format_record` 提供（纯函数，便于测试）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.core import db
from src.core.db import utc_now
from src.models.tables import AuditLog

DEFAULT_LIMIT = 10
MAX_LIMIT = 50


async def record(
    action: str,
    *,
    actor_qq: str = "",
    group_id: str = "",
    detail: str = "",
) -> None:
    """写一条审计记录。"""
    async with db.get_session() as session:
        session.add(
            AuditLog(
                qq=str(actor_qq),
                action=str(action),
                detail=str(detail),
                group_id=str(group_id),
                created_at=utc_now(),
            )
        )
        await session.commit()


async def recent(*, limit: int = DEFAULT_LIMIT, group_id: str | None = None) -> list[AuditLog]:
    """最近的管理操作（新 → 旧）；可只取某个群的。"""
    try:
        wanted = int(limit)
    except (TypeError, ValueError):
        wanted = DEFAULT_LIMIT
    wanted = max(1, min(wanted, MAX_LIMIT))
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(wanted)
    if group_id is not None:
        stmt = stmt.where(AuditLog.group_id == str(group_id))
    async with db.get_session() as session:
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)


def format_record(row: AuditLog, *, tz_name: str = "Asia/Shanghai") -> str:
    """把一条审计记录渲染成一行：``MM-DD HH:MM · 操作者 · 动作 — 详情 [群xxx]``。"""
    when = row.created_at or ""
    try:
        moment = datetime.strptime(row.created_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        when = moment.astimezone(ZoneInfo(tz_name)).strftime("%m-%d %H:%M")
    except Exception:  # noqa: BLE001 - 时间戳异常时原样展示，不让日志功能失效
        pass
    parts = [when, row.qq or "-", row.action]
    line = " · ".join(parts)
    if row.detail:
        line += " — " + row.detail
    if row.group_id:
        line += f"（群 {row.group_id}）"
    return line

