"""admin：管理员命令（P0 只读：查看权限；管理操作在后续阶段加入）。"""
from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata

from src.core import permissions as perms

__plugin_meta__ = PluginMetadata(
    name="admin",
    description="管理员命令（权限查看）",
    usage="/权限 — 查看自己的权限与管理员名单",
)

permission_cmd = on_command("权限", priority=10, block=True)


@permission_cmd.handle()
async def _handle_permission(event: MessageEvent) -> None:
    qq = str(event.user_id)
    role = await perms.get_role(qq)
    if role is None:
        await permission_cmd.finish("你的权限：普通成员")
    lines = [f"你的权限：{role}", "管理员名单："]
    for admin in await perms.list_admins():
        suffix = f"（{admin.note}）" if admin.note else ""
        lines.append(f"· {admin.qq} — {admin.role}{suffix}")
    await permission_cmd.finish("\n".join(lines))
