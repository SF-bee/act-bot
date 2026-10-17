"""权限系统：角色一律存数据库（admins 表），代码中不出现任何 QQ 号。

角色：``owner``（技术负责人，唯一）> ``admin``（管理组）。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.core import db, ids
from src.core.db import utc_now  # 时间戳唯一来源（本模块历史上自己实现过一份）
from src.models.tables import Admin

ROLE_ADMIN = "admin"
ROLE_OWNER = "owner"
VALID_ROLES = (ROLE_ADMIN, ROLE_OWNER)
ROLE_ORDER = {ROLE_ADMIN: 1, ROLE_OWNER: 2}


def _normalize_qq(qq: str | int) -> str:
    """QQ 号校验（口径统一在 src.core.ids）。"""
    return ids.normalize_qq(qq)


async def _owner_excluding(session, qq: str) -> Admin | None:
    """除该 QQ 之外的现有 owner（owner 全局唯一，最多一个）。"""
    rows = (
        await session.execute(
            select(Admin).where(Admin.role == ROLE_OWNER, Admin.qq != qq)
        )
    ).scalars().all()
    return rows[0] if rows else None


async def _commit(session) -> None:
    """提交；唯一索引冲突（并发抢 owner）转成可读的 ValueError。"""
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError(
            "已存在 owner（并发写入被唯一约束拦下），请改用 transfer_owner() 换届"
        ) from exc


async def get_role(qq: str | int) -> str | None:
    """返回该 QQ 的角色（owner / admin）；不是管理员则返回 None。"""
    qq = _normalize_qq(qq)
    async with db.get_session() as session:
        row = (await session.execute(select(Admin).where(Admin.qq == qq))).scalar_one_or_none()
        return row.role if row else None


async def is_admin(qq: str | int) -> bool:
    """是否为管理员（owner 或 admin）——管理命令的通用入口检查。"""
    return await get_role(qq) is not None


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
    """新增或更新管理员；返回是否为新添加。

    owner 全局唯一（迁移 008 的部分唯一索引兜底），因此这里额外两条校验：

    - role=owner 且已存在别的 owner 时抛 ValueError；换届请用 transfer_owner()，
      首次初始化用 scripts/bootstrap_admin.py。
    - 把当前唯一 owner 降级为 admin 时抛 ValueError，避免系统失去 owner。
    """
    qq = _normalize_qq(qq)
    if role not in VALID_ROLES:
        raise ValueError(f"未知角色：{role!r}")
    async with db.get_session() as session:
        row = (await session.execute(select(Admin).where(Admin.qq == qq))).scalar_one_or_none()
        if role == ROLE_OWNER:
            other = await _owner_excluding(session, qq)
            if other is not None:
                raise ValueError(
                    f"已存在 owner {other.qq}，不能添加第二个 owner；"
                    "换届请用 transfer_owner() 或 manage.py admins transfer"
                )
        elif row is not None and row.role == ROLE_OWNER:
            raise ValueError(
                f"{qq} 是当前唯一 owner，不能降级为 {role}；"
                "换届请用 transfer_owner() 或 manage.py admins transfer"
            )
        if row is None:
            session.add(
                Admin(qq=qq, role=role, note=note, created_by=created_by, created_at=utc_now())
            )
            await _commit(session)
            return True
        row.role = role
        if note:
            row.note = note
        await _commit(session)
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
    """转让 owner：旧 owner 降为 admin，新 QQ 升为 owner（幂等）。

    顺序很重要：迁移 008 的唯一索引要求「先降后升」，否则新 owner 的 INSERT/UPDATE
    可能先于旧 owner 的降级落库而撞索引，因此显式 flush() 分隔两步。
    """
    new_qq = _normalize_qq(new_qq)
    async with db.get_session() as session:
        rows = (await session.execute(select(Admin))).scalars().all()
        for row in rows:
            if row.role == ROLE_OWNER and row.qq != new_qq:
                row.role = ROLE_ADMIN
        await session.flush()
        target = next((r for r in rows if r.qq == new_qq), None)
        if target is None:
            session.add(
                Admin(qq=new_qq, role=ROLE_OWNER, note="", created_by=created_by, created_at=utc_now())
            )
        else:
            target.role = ROLE_OWNER
        await _commit(session)
