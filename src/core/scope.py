"""私聊管理群：目标群解析（-g / /use 绑定）。

群内命令自动用当前群；私聊命令用 -g <群号> 单次指定，或先 /use <群号>
绑定默认群。绑定**落库**（admin_bindings 表），启动时回填内存缓存；
读路径（extract_scope / bound_group）同步，写路径（save / remove）异步。
内存缓存只是加速，数据库才是事实来源。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import select

from src.core import db, ids
from src.core.db import utc_now
from src.models.tables import AdminBinding

_bindings: dict[str, str] = {}


def _key(qq: str | int) -> str:
    return str(qq).strip()


def _group_id(value: str | int) -> str:
    """规范化群号：至少 5 位数字，否则返回空串（命令层不抛异常）。"""
    try:
        return ids.normalize_group_id(value)
    except ValueError:
        return ""


def bind(actor_qq: str | int, group_id: str | int) -> str:
    """绑定私聊默认群；返回规范化后的群号（非法时返回空串且不写入）。"""
    gid = _group_id(group_id)
    if gid:
        _bindings[_key(actor_qq)] = gid
    return gid


def bound_group(actor_qq: str | int) -> str:
    """当前私聊绑定的默认群；未绑定返回空串。"""
    return _bindings.get(_key(actor_qq), "")


def clear(actor_qq: str | int) -> None:
    """解除绑定。"""
    _bindings.pop(_key(actor_qq), None)


def normalize_group(value: str | int) -> str:
    """公开的群号规范化（命令层在做副作用前先校验）。"""
    return _group_id(value)


def reset() -> None:
    """清空内存缓存（测试用；不影响数据库）。"""
    _bindings.clear()


async def load_all() -> int:
    """从数据库回填内存缓存（启动时调用），返回绑定条数。"""
    async with db.get_session() as session:
        rows = (await session.execute(select(AdminBinding))).scalars().all()
    _bindings.clear()
    for row in rows:
        qq = _key(row.qq)
        gid = _group_id(row.group_id)
        if qq and gid:
            _bindings[qq] = gid
    return len(_bindings)


async def save(actor_qq: str | int, group_id: str | int) -> str:
    """绑定并落库；返回规范化群号（非法返回空串且不写库）。"""
    gid = _group_id(group_id)
    if not gid:
        return ""
    key = _key(actor_qq)
    _bindings[key] = gid
    async with db.get_session() as session:
        row = (
            await session.execute(select(AdminBinding).where(AdminBinding.qq == key))
        ).scalar_one_or_none()
        if row is None:
            session.add(AdminBinding(qq=key, group_id=gid, updated_at=utc_now()))
        else:
            row.group_id = gid
            row.updated_at = utc_now()
        await session.commit()
    return gid


async def remove(actor_qq: str | int) -> None:
    """解除绑定并删库；不存在时静默。"""
    key = _key(actor_qq)
    _bindings.pop(key, None)
    async with db.get_session() as session:
        row = (
            await session.execute(select(AdminBinding).where(AdminBinding.qq == key))
        ).scalar_one_or_none()
        if row is not None:
            await session.delete(row)
            await session.commit()


@dataclass
class ScopeResult:
    """一次作用域解析的结果。"""

    group_id: str = ""
    tokens: list[str] = field(default_factory=list)
    silent: bool = False
    error: str = ""


def extract_scope(
    tokens: Iterable[str],
    *,
    is_group: bool,
    event_group_id: str = "",
    actor_qq: str = "",
) -> ScopeResult:
    """从命令 token 里解析目标群与 -s 静默标记。

    - -g <群号>：指定目标群（群内不允许，默认就是当前群）
    - -s：静默，不在群里发通告
    """
    remaining: list[str] = []
    explicit = ""
    silent = False
    items = list(tokens)
    index = 0
    while index < len(items):
        token = items[index]
        if token == "-g":
            if index + 1 >= len(items):
                return ScopeResult(error="用法：-g <群号>")
            candidate = _group_id(items[index + 1])
            if not candidate:
                return ScopeResult(error="群号不合法：" + str(items[index + 1]))
            explicit = candidate
            index += 2
            continue
        if token == "-s":
            silent = True
            index += 1
            continue
        remaining.append(token)
        index += 1

    if is_group:
        current = str(event_group_id)
        if explicit and explicit != current:
            return ScopeResult(error="群内无需 -g：默认就是当前群。")
        return ScopeResult(group_id=current, tokens=remaining, silent=silent)
    if explicit:
        return ScopeResult(group_id=explicit, tokens=remaining, silent=silent)
    bound = bound_group(actor_qq)
    if bound:
        return ScopeResult(group_id=bound, tokens=remaining, silent=silent)
    return ScopeResult(
        tokens=remaining,
        silent=silent,
        error="请先 /use <群号> 绑定默认群，或在命令里加 -g <群号>。",
    )
