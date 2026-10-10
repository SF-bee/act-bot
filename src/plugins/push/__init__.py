"""push：定时推送的查看与试发。

推送本身完全是配置驱动的——在 ``config/config.toml`` 里写 ``[[push]]`` 段落即可
（见 ``docs/scheduler.md`` 与 ``src/core/push.py``）；本插件只提供两个管理命令，
方便排查与调文案：

- ``/push``：列出已配置的推送（时间 / 星期 / 目标 / 启停）；
- ``/push test <名称>``：立即按该条配置试发一次（目标不变）。

按命令约定，管理命令用英文规范名、不加入中文别名，并对普通成员静默拒绝。
"""
from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata

from src.core import permissions as perms
from src.core import push
from src.core.config import get_settings

__plugin_meta__ = PluginMetadata(
    name="push",
    description="定时推送（在 config.toml 的 [[push]] 配置，命令用于查看与试发）",
    usage=(
        "/push — 查看已配置的定时推送\n"
        "　/push test <名称> — 立即试发一条"
    ),
    extra={"role": "admin", "order": 70},
)

push_cmd = on_command("push", priority=10, block=True)


def _arguments(event: MessageEvent) -> list[str]:
    return event.message.extract_plain_text().split()[1:]


@push_cmd.handle()
async def _handle_push(event: MessageEvent) -> None:
    if not await perms.is_admin(str(event.user_id)):
        await push_cmd.finish()  # 静默拒绝：不暴露命令存在

    settings = get_settings()
    schedules = settings.pushes
    args = _arguments(event)
    action = args[0].lower() if args else ""

    if action == "test":
        name = args[1] if len(args) > 1 else ""
        schedule = next((item for item in schedules if item.name == name), None)
        if schedule is None:
            names = "、".join(item.name for item in schedules) or "（无）"
            await push_cmd.finish(f"没有名为「{name}」的推送。已配置：{names}")
            return
        sent = await push.send_push(
            schedule, interval_seconds=settings.broadcast_interval_seconds
        )
        await push_cmd.finish(f"「{schedule.name}」试发完成：成功 {sent} 条。")

    if not schedules:
        await push_cmd.finish(
            "还没有配置定时推送。在 config/config.toml 里添加 [[push]] 段落，"
            "重启后生效（见 docs/scheduler.md）。"
        )
    lines = ["已配置的定时推送："]
    lines.extend(f"· {push.describe(item)}" for item in schedules)
    lines.append("试发：/push test <名称>")
    await push_cmd.finish("\n".join(lines))
