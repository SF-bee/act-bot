"""help：命令帮助菜单。

命令清单不手写，而是从各插件的 ``PluginMetadata`` 汇总：
- ``usage`` 一行一个命令；
- ``extra["role"]`` = member / admin（决定谁能看到）；
- ``extra["order"]`` 排序。

所以新增插件只要按约定填好 metadata，帮助菜单会自动收录，不用回来改这里。
"""
from __future__ import annotations

import nonebot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata

from src.core import permissions as perms
from src.core.help import ADMIN_ROLE, HelpEntry, build_entry, render_help

__plugin_meta__ = PluginMetadata(
    name="help",
    description="命令帮助菜单（普通成员与管理员看到的内容不同）",
    usage="/help — 查看可用命令",
    extra={"role": "member", "order": 10},
)

help_cmd = on_command("help", priority=10, block=True)


def collect_entries() -> list[HelpEntry]:
    """汇总已加载插件的帮助条目（无 metadata / 无 usage 的插件跳过）。"""
    entries: list[HelpEntry] = []
    for plugin in nonebot.get_loaded_plugins():
        meta = plugin.metadata
        if meta is None:
            continue
        extra = getattr(meta, "extra", None) or {}
        entry = build_entry(
            usage=getattr(meta, "usage", "") or "",
            role=str(extra.get("role", "member")),
            order=extra.get("order", 100),
        )
        if entry is not None:
            entries.append(entry)
    return entries


@help_cmd.handle()
async def _handle_help(event: MessageEvent) -> None:
    role = await perms.get_role(str(event.user_id))
    header = f"ACT Bot 命令（你的权限：{role or '普通成员'}）"
    await help_cmd.finish(render_help(collect_entries(), is_admin=role is not None, header=header))

