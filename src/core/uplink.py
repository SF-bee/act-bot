"""协议端在线状态：记录「被踢」的时刻，等重新上线后补一条汇总。

为什么单独一层：

- 「掉线」有两种。一是协议端自己重启（日志里 `WebSocket ... closed by peer`，几秒就
  回来）；二是腾讯把登录态吊销（`notice.bot_offline`：「你的账号当前登录已失效」），
  必须人工重新登录。两者看起来都像"机器人不说话"，但只有后者需要人处理——只盯后者。
- 被踢的那一刻账号**已经不在线**了，此时私聊管理员发不出去（实测：下线通知到达后
  3 秒协议端就关掉 WebSocket）。所以不做「掉线即告警」，改成先记下时间，等协议端
  重新连上再发一条汇总——那时账号一定在线，消息一定发得出去。

状态只放内存（进程重启即清空）：它描述的只是「本进程看见的这次掉线」，不值得落库。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from src.core.stats import DEFAULT_TZ, format_duration


@dataclass(frozen=True)
class Outage:
    """一次掉线：掉线时刻、掉之前在线了多久、协议端给的说法。"""

    self_id: str
    at: float
    online_seconds: float | None = None
    detail: str = ""


@dataclass(frozen=True)
class Recovery:
    """一次恢复：对应的掉线记录 + 离线时长 + 恢复时刻。"""

    outage: Outage
    at: float
    offline_seconds: float


_pending: dict[str, Outage] = {}
_online_since: dict[str, float] = {}


def _moment(now: float | None) -> float:
    return time.time() if now is None else float(now)


def mark_online(self_id: str | int, *, now: float | None = None) -> Recovery | None:
    """协议端连上：返回本次恢复（没有掉线记录则返回 None，例如进程启动后的首次上线）。

    每个掉线记录只会被消费一次——重复触发连接钩子不会重复提醒。
    """
    key = str(self_id)
    moment = _moment(now)
    outage = _pending.pop(key, None)
    _online_since[key] = moment
    if outage is None:
        return None
    return Recovery(outage=outage, at=moment, offline_seconds=max(0.0, moment - outage.at))


def mark_offline(self_id: str | int, *, detail: str = "", now: float | None = None) -> Outage:
    """协议端掉线：记下这次掉线，返回记录（含本次在线时长，未知为 None）。"""
    key = str(self_id)
    moment = _moment(now)
    started = _online_since.pop(key, None)
    outage = Outage(
        self_id=key,
        at=moment,
        online_seconds=None if started is None else max(0.0, moment - started),
        detail=str(detail or "").strip(),
    )
    _pending[key] = outage
    return outage


def pending(self_id: str | int) -> Outage | None:
    """该账号当前未恢复的掉线记录；没有则为 None。"""
    return _pending.get(str(self_id))


def reset() -> None:
    """清空全部状态（测试用）。"""
    _pending.clear()
    _online_since.clear()


def _stamp(moment: float, tz_name: str) -> str:
    return datetime.fromtimestamp(float(moment), ZoneInfo(tz_name)).strftime("%m-%d %H:%M")


def render_offline(outage: Outage, *, tz_name: str = DEFAULT_TZ) -> str:
    """一行式掉线描述（写日志用）。"""
    parts = ["掉线时间 {0}".format(_stamp(outage.at, tz_name))]
    if outage.online_seconds is not None:
        parts.append("本次在线 {0}".format(format_duration(outage.online_seconds)))
    if outage.detail:
        parts.append(outage.detail)
    return "｜".join(parts)


def render_recovery(
    recovery: Recovery,
    *,
    bot_name: str = "",
    bot_title: str = "",
    tz_name: str = DEFAULT_TZ,
) -> str:
    """渲染补发给管理员的汇总（纯函数，便于测试）。"""
    head = "协议端掉线提醒"
    if bot_name:
        head = "{0}（{1}）· {2}".format(bot_name, bot_title, head)
    outage = recovery.outage
    line = "· 掉线 {0}".format(_stamp(outage.at, tz_name))
    if outage.online_seconds is not None:
        line += "（掉线前已在线 {0}）".format(format_duration(outage.online_seconds))
    lines = [
        head,
        line,
        "· 离线 {0}，{1} 已重新上线".format(
            format_duration(recovery.offline_seconds), _stamp(recovery.at, tz_name)
        ),
    ]
    if outage.detail:
        lines.append("· 协议端说明：{0}".format(outage.detail))
    return "\n".join(lines)
