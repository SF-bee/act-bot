"""权限系统：角色一律存数据库（admins 表），代码中不出现任何 QQ 号。

角色：``owner``（技术负责人，唯一）> ``admin``（管理组）。
"""
from __future__ import annotations

from sqlalchemy import select

from src.core import db
from src.core.db import utc_now  # 时间戳唯一来源（本模块历史上自己实现过一份）
from src.models.tables import Admin

ROLE_ADMIN = "admin"
ROLE_OWNER = "owner"
VALID_ROLES = (ROLE_ADMIN, ROLE_OWNER)
ROLE_ORDER = {ROLE_ADMIN: 1, ROLE_OWNER: 2}


def _normalize_qq(qq: str | int) -> str:
    value = str(qq).strip()
    if not value.isdigit() or len(value) < 5:
        raise ValueError(f"QQ 号格式不正确：{qq!r}")
    return value


async def get_role(qq: str | int) -> str | None:
    """返回该 QQ 的角色（owner / admin）；不是管理员则返回 None。"""
    qq = _normalize_qq(qq)
    async with db.get_session() as session:
        row = (await session.execute(select(Admin).where(Admin.qq == qq))).scalar_one_or_none()
        return row.role if row else None


async def has_role(qq: str | int, required: str) -> bool:
    """判断该 QQ 是否达到 ``required`` 角色（等级比较）。"""
    if required not in ROLE_ORDER:
        raise ValueError(f"未知角色：{required!r}")
    role = await get_role(qq)
    return role is not None and ROLE_ORDER[role] >= ROLE_ORDER[required]


async def list_admins() -> list[Admin]:
    """全部管理员（owner 在前）。"""
    async with db.get_session() as session:
        rows = (
            await session.execute(select(Admin).order_by(Admin.role.desc(), Admin.qq.asc()))
        ).scalars().all()
        return list(rows)


async def add_admin(
    qq: str | int,
    role: str = ROLE_ADMIN,
    note: str = "",
    created_by: str = "",
) -> bool:
    """新增或更新管理员；返回是否为新添加。"""
    qq = _normalize_qq(qq)
    if role not in VALID_ROLES:
        raise ValueError(f"未知角色：{role!r}")
    async with db.get_session() as session:
        row = (await session.execute(select(Admin).where(Admin.qq == qq))).scalar_one_or_none()
        if row is None:
            session.add(
                Admin(qq=qq, role=role, note=note, created_by=created_by, created_at=utc_now())
            )
            await session.commit()
            return True
        row.role = role
        if note:
            row.note = note
        await session.commit()
        return False


async def remove_admin(qq: str | int) -> bool:
    """移除管理员；不存在返回 False。"""
    qq = _normalize_qq(qq)
    async with db.get_session() as session:
        row = (await session.execute(select(Admin).where(Admin.qq == qq))).scalar_one_or_none()
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True


async def transfer_owner(new_qq: str | int, created_by: str = "") -> None:
    """转让 owner：旧 owner 降为 admin，新 QQ 升为 owner。"""
    new_qq = _normalize_qq(new_qq)
    async with db.get_session() as session:
        rows = (await session.execute(select(Admin))).scalars().all()
        for row in rows:
            if row.role == ROLE_OWNER and row.qq != new_qq:
                row.role = ROLE_ADMIN
        target = next((r for r in rows if r.qq == new_qq), None)
        if target is None:
            session.add(
                Admin(qq=new_qq, role=ROLE_OWNER, note="", created_by=created_by, created_at=utc_now())
            )
        else:
            target.role = ROLE_OWNER
        await session.commit()
