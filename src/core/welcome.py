"""入群欢迎的纯逻辑：欢迎语渲染 + 命令参数解析。

放在 core 而非插件里：这些函数不依赖 nonebot 的插件机制（matcher 注册），可以单独测试。
重复入群事件的防护已上移到事件中枢的 cooldown（见 src/core/events.py），这里不再自带去重。
"""
from __future__ import annotations

from nonebot.adapters.onebot.v11 import Message, MessageSegment

# 管理命令 /welcome 的子命令（命令名与参数一律英文，方便输入）
VALID_ACTIONS = ("on", "off")


def render_welcome(
    template: str,
    *,
    nickname: str,
    group_name: str,
    user_id: str,
    at_newcomer: bool = True,
    bot_name: str = "",
    bot_title: str = "",
) -> Message:
    """把欢迎语模板渲染成消息。

    占位符：{nickname} 新人在群里的显示名、{group_name} 群名、{user_id} QQ 号、
    {bot_name} 机器人人设名、{bot_title} 机器人身份；未知占位符原样保留。
    ``at_newcomer`` 为真时先 @ 新人再换行。
    """
    text = template
    for key, value in (
        ("nickname", nickname),
        ("group_name", group_name),
        ("user_id", user_id),
        ("bot_name", bot_name),
        ("bot_title", bot_title),
    ):
        text = text.replace("{" + key + "}", value)
    message = Message()
    if at_newcomer:
        message += MessageSegment.at(user_id)
        message += MessageSegment.text("\n")
    message += MessageSegment.text(text)
    return message


def parse_action(text: str) -> str:
    """解析 /welcome 的子命令：""（查看状态）/ "on" / "off" / "unknown"。

    第一段是命令本身（含前缀），忽略；只认第二段，大小写不敏感。
    """
    parts = text.strip().split()
    if len(parts) < 2:
        return ""
    action = parts[1].strip().lower()
    return action if action in VALID_ACTIONS else "unknown"

