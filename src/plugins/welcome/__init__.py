"""welcome：入群欢迎。

有人入群（notice.group_increase）时自动发欢迎语。两级开关：
- 全局：config/config.toml 的 [features].welcome（关掉则整个功能不响应）
- 群级：groups 表的 welcome_on（群内用 /欢迎 开|关）

管理员命令：
- /欢迎            查看本群开关与欢迎语预览
- /欢迎 开|关      切换本群入群欢迎

渲染与去重的纯逻辑在 src/core/welcome.py；本文件只做接线与权限判断。
"""
from __future__ import annotations

import logging

from nonebot import on_command, on_notice
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    MessageEvent,
    MessageSegment,
    NoticeEvent,
)
from nonebot.plugin import PluginMetadata

from src.core import groups
from src.core import permissions as perms
from src.core.config import get_settings
from src.core.welcome import is_duplicate, render_welcome

logger = logging.getLogger("actbot.welcome")

__plugin_meta__ = PluginMetadata(
    name="welcome",
    description="入群欢迎（管理员可开关）",
    usage="/欢迎 — 查看本群入群欢迎开关与欢迎语预览\n/欢迎 开|关 — 切换本群入群欢迎",
)

group_increase = on_notice(priority=10, block=False)
welcome_cmd = on_command("欢迎", priority=10, block=True)


async def _member_label(bot: Bot, group_id: str, user_id: str) -> str:
    """新人在群里的显示名（群名片优先）；取不到则退回 QQ 号。"""
    try:
        info = await bot.get_group_member_info(
            group_id=int(group_id), user_id=int(user_id), no_cache=True
        )
        return str(info.get("card") or info.get("nickname") or user_id)
    except Exception:  # noqa: BLE001 - 取昵称失败不影响欢迎
        logger.debug("获取群成员信息失败，退回 QQ 号：group=%s user=%s", group_id, user_id)
        return user_id


async def _group_name(bot: Bot, group_id: str) -> str:
    """群名；取不到则返回空串。"""
    try:
        info = await bot.get_group_info(group_id=int(group_id))
        return str(info.get("group_name") or "")
    except Exception:  # noqa: BLE001 - 取群名失败不影响欢迎
        logger.debug("获取群信息失败：group=%s", group_id)
        return ""


@group_increase.handle()
async def _handle_group_increase(bot: Bot, event: NoticeEvent) -> None:
    if not isinstance(event, GroupIncreaseNoticeEvent):
        return
    settings = get_settings()
    if not settings.feature("welcome"):
        return
    group_id, user_id = str(event.group_id), str(event.user_id)
    if user_id == str(event.self_id):
        logger.info("机器人自身被拉入群 %s，跳过欢迎", group_id)
        return
    if is_duplicate(group_id, user_id):
        logger.debug("忽略重复入群事件：group=%s user=%s", group_id, user_id)
        return
    if not await groups.welcome_enabled(group_id):
        logger.info("群 %s 已关闭入群欢迎，跳过", group_id)
        return
    message = render_welcome(
        settings.welcome_text,
        nickname=await _member_label(bot, group_id, user_id),
        group_name=await _group_name(bot, group_id),
        user_id=user_id,
        at_newcomer=settings.welcome_at_newcomer,
    )
    try:
        await bot.send_group_msg(group_id=event.group_id, message=message)
    except Exception:  # noqa: BLE001 - 发送失败只记日志，不影响其它事件处理
        logger.exception("发送入群欢迎失败：group=%s user=%s", group_id, user_id)
        return
    logger.info("已发送入群欢迎：group=%s user=%s", group_id, user_id)


@welcome_cmd.handle()
async def _handle_welcome_cmd(bot: Bot, event: MessageEvent) -> None:
    if await perms.get_role(str(event.user_id)) is None:
        await welcome_cmd.finish()  # 非管理员：静默，不暴露管理命令
    if not isinstance(event, GroupMessageEvent):
        await welcome_cmd.finish("这个命令要在群里用哦。")
    parts = event.message.extract_plain_text().strip().split()
    action = parts[1].strip() if len(parts) > 1 else ""
    group_id = str(event.group_id)
    settings = get_settings()

    if action in ("开", "开启", "on"):
        await groups.set_welcome_enabled(
            group_id, True, name=await _group_name(bot, group_id)
        )
        await welcome_cmd.finish("好，本群入群欢迎已开启。")
    if action in ("关", "关闭", "off"):
        await groups.set_welcome_enabled(group_id, False)
        await welcome_cmd.finish("好，本群入群欢迎已关闭。")

    enabled = await groups.welcome_enabled(group_id)
    global_on = settings.feature("welcome")
    preview = render_welcome(
        settings.welcome_text,
        nickname="新同学",
        group_name=await _group_name(bot, group_id),
        user_id=str(event.user_id),
        at_newcomer=settings.welcome_at_newcomer,
    )
    head = MessageSegment.text(
        "入群欢迎（本群）：" + ("已开启" if enabled else "已关闭")
        + "\n全局开关：" + ("已开启" if global_on else "已关闭（[features].welcome）")
        + "\n欢迎语预览：\n"
    )
    await welcome_cmd.finish(head + preview)

