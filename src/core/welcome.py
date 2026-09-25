"""入群欢迎的纯逻辑：消息渲染 + 短时去重。

放在 core 而非插件里：这些函数不依赖 nonebot 的插件机制（matcher 注册），
可以单独测试；插件只负责事件接线与权限判断。
"""
from __future__ import annotations

import time

from nonebot.adapters.onebot.v11 import Message, MessageSegment

# 同一个人短时间内重复入群事件只欢迎一次（协议端偶发重推）
DEDUP_WINDOW_SECONDS = 60.0
_recent: dict[tuple[str, str], float] = {}


def render_welcome(
    template: str,
    *,
    nickname: str,
    group_name: str,
    user_id: str,
    at_newcomer: bool = True,
) -> Message:
    """把欢迎语模板渲染成消息。

    占位符：{nickname} 新人在群里的显示名、{group_name} 群名、{user_id} QQ 号；
    未知占位符原样保留。``at_newcomer`` 为真时先 @ 新人再换行。
    """
    text = template
    for key, value in (
        ("nickname", nickname),
        ("group_name", group_name),
        ("user_id", user_id),
    ):
        text = text.replace("{" + key + "}", value)
    message = Message()
    if at_newcomer:
        message += MessageSegment.at(user_id)
        message += MessageSegment.text("\n")
    message += MessageSegment.text(text)
    return message


def is_duplicate(group_id: str, user_id: str, now: float | None = None) -> bool:
    """同一（群, 人）在窗口期内重复出现则返回 True；同时刷新最近记录。"""
    moment = time.monotonic() if now is None else now
    key = (str(group_id), str(user_id))
    last = _recent.get(key)
    if last is not None and moment - last < DEDUP_WINDOW_SECONDS:
        return True
    _recent[key] = moment
    if len(_recent) > 512:  # 顺手清理，避免长期运行无限增长
        for item, stamp in list(_recent.items()):
            if moment - stamp > DEDUP_WINDOW_SECONDS:
                _recent.pop(item, None)
    return False


def reset_dedup() -> None:
    """清空去重记录（测试用）。"""
    _recent.clear()

