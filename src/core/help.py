"""帮助菜单的纯逻辑：汇总各插件声明的命令，按角色过滤后渲染。

约定（插件侧只需声明，不用改这里）：
- ``PluginMetadata.usage``：一行一个命令，形如 ``/cmd — 说明``；
- ``PluginMetadata.extra["role"]``：``member``（默认，所有人可见）或 ``admin``（仅管理员）；
- ``PluginMetadata.extra["order"]``：排序权重，越小越靠前（默认 100）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

MEMBER_ROLE = "member"
ADMIN_ROLE = "admin"
DEFAULT_ORDER = 100


@dataclass(frozen=True)
class HelpEntry:
    """一个插件的帮助条目（lines 即 usage 的每一行）。"""

    lines: tuple[str, ...]
    role: str = MEMBER_ROLE
    order: int = DEFAULT_ORDER


def parse_usage(usage: str | None) -> tuple[str, ...]:
    """把 usage 文本拆成非空行。"""
    if not usage:
        return ()
    return tuple(line.strip() for line in str(usage).splitlines() if line.strip())


def build_entry(
    *, usage: str | None, role: str = MEMBER_ROLE, order: int = DEFAULT_ORDER
) -> HelpEntry | None:
    """按约定组装条目；usage 为空则该插件不进帮助菜单。"""
    lines = parse_usage(usage)
    if not lines:
        return None
    try:
        weight = int(order)
    except (TypeError, ValueError):
        weight = DEFAULT_ORDER
    return HelpEntry(lines=lines, role=str(role or MEMBER_ROLE), order=weight)


def _sort_key(entry: HelpEntry) -> tuple[int, str]:
    return (entry.order, entry.lines[0] if entry.lines else "")


def _section(title: str, entries: Sequence[HelpEntry]) -> list[str]:
    out = ["", title + "："]
    if not entries:
        out.append("· （暂无）")
        return out
    for entry in entries:
        out.extend("· " + line for line in entry.lines)
    return out


def render_help(
    entries: Iterable[HelpEntry],
    *,
    is_admin: bool,
    header: str = "",
) -> str:
    """渲染帮助文本：普通成员只看到 member 条目，管理员额外看到 admin 条目。"""
    all_entries = sorted(entries, key=_sort_key)
    member_entries = [e for e in all_entries if e.role != ADMIN_ROLE]
    admin_entries = [e for e in all_entries if e.role == ADMIN_ROLE]
    lines: list[str] = []
    if header:
        lines.append(header)
    lines.extend(_section("常用命令", member_entries))
    if is_admin:
        lines.extend(_section("管理员命令", admin_entries))
    return "\n".join(lines).strip()

