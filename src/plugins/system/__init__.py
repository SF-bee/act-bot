"""system：基础系统命令（连通性检查）。"""
from __future__ import annotations

from nonebot import on_command
from nonebot.plugin import PluginMetadata

import src
from src.core import persona
from src.core.config import get_settings

__plugin_meta__ = PluginMetadata(
    name="system",
    description="基础系统命令（连通性检查）",
    usage="/ping — 检查机器人连通性\n/version — 查看版本与运行信息",
    extra={"role": "member", "order": 20},
)

ping = on_command("ping", priority=10, block=True)


@ping.handle()
async def _handle_ping() -> None:
    await ping.finish("pong")


version = on_command("version", priority=10, block=True)


@version.handle()
async def _handle_version() -> None:
    settings = get_settings()
    enabled = sum(1 for value in settings.features.values() if value)
    await version.finish(
        f"{persona.intro()} · v{src.__version__}"
        f"｜功能开关 {enabled}/{len(settings.features)}｜文档见仓库 docs/"
    )
