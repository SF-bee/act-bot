"""console：管理控制台（群功能开关 + 审计记录）。仅管理员可用。

- `/config`               查看本群各功能开关（全局开关 | 本群开关）
- `/config <功能>`        只看某一个功能
- `/config <功能> on|off` 开关本群功能（写 groups.features，并记审计）
- `/audit [n]`            查看最近 n 条管理操作（默认 10，最多 50）

功能名册见 src/core/features.py；群开关读写见 src/core/groups.py。
"""
from __future__ import annotations

import logging

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.plugin import PluginMetadata

from src.core import audit, features, groups
from src.core import permissions as perms
from src.core.config import get_settings
from src.core.onebot import safe_group_name

logger = logging.getLogger("actbot.console")

__plugin_meta__ = PluginMetadata(
    name="console",
    description="管理控制台：群功能开关与审计记录（仅管理员）",
    usage="/config — 查看本群各功能开关\n/config <功能> on|off — 开关本群功能\n/audit [n] — 查看最近 N 条管理操作",
    extra={"role": "admin", "order": 120},
)

config_cmd = on_command("config", priority=10, block=True)
audit_cmd = on_command("audit", priority=10, block=True)


def _switch_text(enabled: bool) -> str:
    return "开" if enabled else "关"


async def _feature_lines(group_id: str, selected: features.Feature | None) -> list[str]:
    """渲染功能开关列表。"""
    settings = get_settings()
    targets = (selected,) if selected is not None else features.all_features()
    lines = ["本群功能开关（全局｜本群）："]
    for item in targets:
        assert item is not None
        group_on = await groups.feature_enabled(group_id, item.name, default=item.default)
        global_on = settings.feature(item.name)
        lines.append(
            "· {0}（{1}）：{2}｜{3}　{4}".format(
                item.label, item.name, _switch_text(global_on), _switch_text(group_on), item.description
            )
        )
    return lines


@config_cmd.handle()
async def _handle_config(bot: Bot, event: MessageEvent) -> None:
    if not await perms.is_admin(str(event.user_id)):
        await config_cmd.finish()  # 非管理员：静默
    if not isinstance(event, GroupMessageEvent):
        await config_cmd.finish("群配置命令要在群里用。")

    name, action = groups.parse_feature_command(event.message.extract_plain_text())
    group_id = str(event.group_id)

    if action == "unknown":
        await config_cmd.finish("用法：/config <功能> on|off（功能名见 /config）")

    selected: features.Feature | None = None
    if name:
        selected = features.get(name)
        if selected is None:
            await config_cmd.finish(
                "没有这个功能：{0}\n可用功能：{1}".format(name, "、".join(features.names()))
            )

    if selected is not None and action in ("on", "off"):
        enabled = action == "on"
        group_name = await safe_group_name(bot, group_id)
        await groups.set_feature(group_id, selected.name, enabled, group_name=group_name)
        await audit.record(
            "config.set",
            actor_qq=str(event.user_id),
            group_id=group_id,
            detail="{0}={1}".format(selected.name, action),
        )
        await config_cmd.finish(
            "{0}：本群已{1}".format(selected.label, "开启" if enabled else "关闭")
        )

    lines = await _feature_lines(group_id, selected)
    if selected is None:
        lines.append("开关：/config <功能> on|off")
    await config_cmd.finish("\n".join(lines))


@audit_cmd.handle()
async def _handle_audit(event: MessageEvent) -> None:
    if not await perms.is_admin(str(event.user_id)):
        await audit_cmd.finish()
    parts = event.message.extract_plain_text().strip().split()
    limit = audit.DEFAULT_LIMIT
    if len(parts) > 1:
        try:
            limit = int(parts[1])
        except ValueError:
            await audit_cmd.finish("用法：/audit [条数]（1-50，默认 10）")
    rows = await audit.recent(limit=limit)
    if not rows:
        await audit_cmd.finish("暂无管理操作记录。")
    tz_name = get_settings().timezone
    lines = ["最近 {0} 条管理操作：".format(len(rows))]
    lines.extend("· " + audit.format_record(row, tz_name=tz_name) for row in rows)
    await audit_cmd.finish("\n".join(lines))

