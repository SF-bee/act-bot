"""welcome：入群欢迎（事件中枢的第一个消费者）。

- 订阅 `GroupMemberJoin`（feature=welcome，cooldown=60 防协议端重复推送）
- 两级开关：全局 `[features].welcome`（config.toml）＋ 群级 groups.features["welcome"]
- 管理员命令：`/welcome`（状态 + 预览）、`/welcome on|off`

群级门控与 cooldown 由事件中枢统一处理，本文件不再直接挂 OneBot 事件；
渲染逻辑在 src/core/welcome.py。
"""
from __future__ import annotations

import logging

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata

from src.core import audit, features, groups
from src.core import permissions as perms
from src.core.config import get_settings
from src.core.events import GroupMemberJoin, subscribe
from src.core.onebot import safe_group_name, safe_member_label
from src.core.welcome import parse_action, render_welcome

logger = logging.getLogger("actbot.welcome")

__plugin_meta__ = PluginMetadata(
    name="welcome",
    description="入群欢迎（管理员可开关）",
    usage="/welcome — 查看本群入群欢迎开关与欢迎语预览\n/welcome on|off — 开启 / 关闭本群入群欢迎",
    extra={"role": "admin", "order": 110},
)

welcome_cmd = on_command("welcome", priority=10, block=True)


@subscribe(
    GroupMemberJoin,
    feature=features.FEATURE_WELCOME,
    cooldown=60,
    name="welcome",
)
async def _on_member_join(event: GroupMemberJoin, bot: Bot) -> None:
    """有人入群 → @ 新人并发送欢迎语（群级开关由中枢门控）。"""
    settings = get_settings()
    if not settings.feature(features.FEATURE_WELCOME):
        return
    if event.user_id == str(getattr(bot, "self_id", "")):
        logger.info("机器人自身被拉入群 %s，跳过欢迎", event.group_id)
        return
    message = render_welcome(
        settings.welcome_text,
        nickname=await safe_member_label(bot, event.group_id, event.user_id),
        group_name=await safe_group_name(bot, event.group_id),
        user_id=event.user_id,
        at_newcomer=settings.welcome_at_newcomer,
    )
    try:
        await bot.send_group_msg(group_id=int(event.group_id), message=message)
    except Exception:  # noqa: BLE001 - 发送失败只记日志
        logger.exception("发送入群欢迎失败：group=%s user=%s", event.group_id, event.user_id)
        return
    logger.info("已发送入群欢迎：group=%s user=%s", event.group_id, event.user_id)


@welcome_cmd.handle()
async def _handle_welcome_cmd(bot: Bot, event: MessageEvent) -> None:
    if not await perms.is_admin(str(event.user_id)):
        await welcome_cmd.finish()  # 非管理员：静默，不暴露管理命令
    if not isinstance(event, GroupMessageEvent):
        await welcome_cmd.finish("这个命令要在群里用哦。")
    action = parse_action(event.message.extract_plain_text())
    group_id = str(event.group_id)
    settings = get_settings()

    if action in ("on", "off"):
        enabled = action == "on"
        group_name = await safe_group_name(bot, group_id)
        await groups.set_feature(
            group_id, features.FEATURE_WELCOME, enabled, group_name=group_name
        )
        await audit.record(
            "welcome.on" if enabled else "welcome.off",
            actor_qq=str(event.user_id),
            group_id=group_id,
            detail=group_name,
        )
        await welcome_cmd.finish("好，本群入群欢迎已开启。" if enabled else "好，本群入群欢迎已关闭。")
    if action == "unknown":
        await welcome_cmd.finish("用法：/welcome 查看状态；/welcome on 开启；/welcome off 关闭。")

    enabled = await groups.feature_enabled(group_id, features.FEATURE_WELCOME)
    global_on = settings.feature(features.FEATURE_WELCOME)
    preview = render_welcome(
        settings.welcome_text,
        nickname="新同学",
        group_name=await safe_group_name(bot, group_id),
        user_id=str(event.user_id),
        at_newcomer=settings.welcome_at_newcomer,
    )
    head = MessageSegment.text(
        "入群欢迎（本群）：" + ("已开启" if enabled else "已关闭")
        + "\n全局开关：" + ("已开启" if global_on else "已关闭（[features].welcome）")
        + "\n欢迎语预览：\n"
    )
    await welcome_cmd.finish(head + preview)

