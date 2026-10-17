"""事件中枢：把 OneBot 原始事件规范化成领域事件并分发。

刻意只做四件事（不追求做通用事件框架）：
1. **规范化**：OneBot 事件 → :class:`DomainEvent`，消费者不碰协议细节；
2. **群级门控**：消费者声明 ``feature``，该功能在本群关掉时不投递；
3. **分发与隔离**：单个消费者抛异常不影响其它消费者；
4. **cooldown**：可声明最小间隔（按 群 + 触发者 维度），用于防抖/防刷屏。

消费者（插件）用法::

    from src.core.events import GroupMemberJoin, subscribe

    @subscribe(GroupMemberJoin, feature="welcome", cooldown=60, name="welcome")
    async def on_join(event: GroupMemberJoin, bot: Bot) -> None:
        ...

注意：领域事件一律用关键字构造（字段顺序不作为契约）。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from src.core import features, groups

logger = logging.getLogger("actbot.events")


# ---------- 领域事件 ----------

class DomainEvent:
    """领域事件标记基类（不承载字段，避免子类字段顺序踩坑）。"""


@dataclass(frozen=True)
class MessageReceived(DomainEvent):
    """收到消息（群或私聊）。"""

    group_id: str = ""
    user_id: str = ""
    message_id: str = ""
    text: str = ""
    is_group: bool = True
    at_self: bool = False  # 消息里是否 @ 了机器人（聊天引擎的唤醒方式之一）
    at_all: bool = False  # 消息里是否 @ 了全体成员（风控用）
    sender_role: str = ""  # 群主 owner / 管理员 admin / 成员 member（风控豁免用）
    raw: Any = None


@dataclass(frozen=True)
class GroupMemberJoin(DomainEvent):
    """有人入群。"""

    group_id: str = ""
    user_id: str = ""
    operator_id: str = ""
    sub_type: str = ""
    raw: Any = None


@dataclass(frozen=True)
class GroupMemberLeave(DomainEvent):
    """有人退群 / 被踢。``sub_type``：leave / kick / kick_me。"""

    group_id: str = ""
    user_id: str = ""
    operator_id: str = ""
    sub_type: str = ""
    raw: Any = None


@dataclass(frozen=True)
class MessageRecalled(DomainEvent):
    """消息被撤回：``user_id`` 是原作者，``operator_id`` 是执行者。"""

    group_id: str = ""
    user_id: str = ""
    operator_id: str = ""
    message_id: str = ""
    raw: Any = None


@dataclass(frozen=True)
class MemberMuted(DomainEvent):
    """成员被禁言。"""

    group_id: str = ""
    user_id: str = ""
    operator_id: str = ""
    duration: int = 0
    raw: Any = None


@dataclass(frozen=True)
class MemberUnmuted(DomainEvent):
    """成员被解除禁言。"""

    group_id: str = ""
    user_id: str = ""
    operator_id: str = ""
    duration: int = 0
    raw: Any = None


def _mentions_self(event: Any) -> bool:
    """消息里是否 @ 了机器人。

    两个来源都看，缺一不可：
    - ``raw_message``（CQ 文本，协议端必给）——**最可靠**：实测某些协议端/适配器
      会把 @ 机器人自己的段从 ``message`` 里剥掉，只剩 ``raw_message`` 还留着；
    - ``message`` 消息段——兼容不带 raw_message 的极简实现。
    """
    self_id = str(getattr(event, "self_id", "") or "")
    if not self_id:
        return False
    raw = str(getattr(event, "raw_message", "") or "")
    for pattern in ("[CQ:at,qq={0}]", '[CQ:at,qq="{0}"]'):
        if pattern.format(self_id) in raw:
            return True
    try:
        segments = list(getattr(event, "message", None))
    except TypeError:  # 没有消息段列表：只按 raw_message 判断
        return False
    for segment in segments:
        if getattr(segment, "type", "") != "at":
            continue
        data = getattr(segment, "data", {}) or {}
        if str(data.get("qq", "")) == self_id:
            return True
    return False


def _mentions_all(event: Any) -> bool:
    """消息里是否 @ 了全体成员。

    与 _mentions_self 对称：raw_message 与消息段两个来源都看。
    """
    raw = str(getattr(event, "raw_message", "") or "")
    if "[CQ:at,qq=all]" in raw or '[CQ:at,qq="all"]' in raw:
        return True
    try:
        segments = list(getattr(event, "message", None))
    except TypeError:
        return False
    for segment in segments:
        if getattr(segment, "type", "") != "at":
            continue
        data = getattr(segment, "data", {}) or {}
        if str(data.get("qq", "")).lower() == "all":
            return True
    return False


def normalize(event: Any) -> DomainEvent | None:
    """OneBot 事件 → 领域事件；不关心的事件返回 None（纯函数，便于测试）。"""
    from nonebot.adapters.onebot.v11 import (
        GroupBanNoticeEvent,
        GroupDecreaseNoticeEvent,
        GroupIncreaseNoticeEvent,
        GroupMessageEvent,
        GroupRecallNoticeEvent,
        MessageEvent,
    )

    if isinstance(event, GroupMessageEvent):
        return MessageReceived(
            group_id=str(event.group_id),
            user_id=str(event.user_id),
            message_id=str(event.message_id),
            text=event.message.extract_plain_text(),
            is_group=True,
            at_self=_mentions_self(event),
            at_all=_mentions_all(event),
            sender_role=str(getattr(getattr(event, "sender", None), "role", "") or ""),
            raw=event,
        )
    if isinstance(event, GroupIncreaseNoticeEvent):
        return GroupMemberJoin(
            group_id=str(event.group_id),
            user_id=str(event.user_id),
            operator_id=str(getattr(event, "operator_id", "") or ""),
            sub_type=str(getattr(event, "sub_type", "") or ""),
            raw=event,
        )
    if isinstance(event, GroupDecreaseNoticeEvent):
        return GroupMemberLeave(
            group_id=str(event.group_id),
            user_id=str(event.user_id),
            operator_id=str(getattr(event, "operator_id", "") or ""),
            sub_type=str(getattr(event, "sub_type", "") or ""),
            raw=event,
        )
    if isinstance(event, GroupRecallNoticeEvent):
        return MessageRecalled(
            group_id=str(event.group_id),
            user_id=str(event.user_id),
            operator_id=str(getattr(event, "operator_id", "") or ""),
            message_id=str(event.message_id),
            raw=event,
        )
    if isinstance(event, GroupBanNoticeEvent):
        muted = str(getattr(event, "sub_type", "") or "") != "lift_ban"
        payload = {
            "group_id": str(event.group_id),
            "user_id": str(event.user_id),
            "operator_id": str(getattr(event, "operator_id", "") or ""),
            "duration": int(getattr(event, "duration", 0) or 0),
            "raw": event,
        }
        return MemberMuted(**payload) if muted else MemberUnmuted(**payload)
    if isinstance(event, MessageEvent):
        return MessageReceived(
            user_id=str(event.user_id),
            message_id=str(event.message_id),
            text=event.message.extract_plain_text(),
            is_group=False,
            raw=event,
        )
    return None


# ---------- 订阅与分发 ----------

Handler = Callable[[DomainEvent, Any], Awaitable[None]]
GateCallable = Callable[[str, str], Awaitable[bool]]


@dataclass(frozen=True)
class Subscription:
    """一个消费者订阅：事件类型 + 处理函数 + 门控参数。"""

    event_type: type[DomainEvent]
    handler: Handler
    feature: str | None = None
    cooldown: float = 0.0
    name: str = ""


@dataclass
class DispatchReport:
    """一次分发的统计（便于测试与排障）。"""

    event_type: str = ""
    matched: int = 0
    delivered: int = 0
    gated: int = 0
    cooled: int = 0
    failed: int = 0


_subscriptions: list[Subscription] = []
_cooldown_seen: dict[tuple[str, str, str], float] = {}
_MAX_COOLDOWN_ENTRIES = 1024


def subscribe(
    event_type: type[DomainEvent],
    *,
    feature: str | None = None,
    cooldown: float = 0.0,
    name: str = "",
) -> Callable[[Handler], Handler]:
    """注册一个消费者（装饰器）；返回原函数。

    ``feature`` 对应 src.core.features 里的功能名；``cooldown`` 单位秒，
    按 (消费者, 群, 触发者) 维度生效——例如入群欢迎用它防协议端重复推送。
    """

    def decorator(handler: Handler) -> Handler:
        _subscriptions.append(
            Subscription(
                event_type=event_type,
                handler=handler,
                feature=str(feature) if feature else None,
                cooldown=float(cooldown or 0.0),
                name=name or getattr(handler, "__name__", "handler"),
            )
        )
        return handler

    return decorator


def subscriptions(event_type: type[DomainEvent] | None = None) -> list[Subscription]:
    """当前订阅列表（可按事件类型过滤）。"""
    if event_type is None:
        return list(_subscriptions)
    return [item for item in _subscriptions if item.event_type is event_type]


def clear_subscriptions() -> None:
    """清空订阅与 cooldown 记录（测试用）。"""
    _subscriptions.clear()
    _cooldown_seen.clear()


async def _default_gate(group_id: str, feature: str) -> bool:
    """默认门控：查群级开关，回退到功能注册表里的默认值。"""
    return await groups.feature_enabled(group_id, feature, default=features.default_of(feature))


CooldownKey = tuple[str, str, str]
_NO_PREVIOUS = object()


def _cooldown_key(sub: Subscription, event: DomainEvent) -> CooldownKey:
    """cooldown 维度：(消费者, 群, 触发者)。"""
    return (sub.name, str(getattr(event, "group_id", "")), str(getattr(event, "user_id", "")))


def _cooldown_available(sub: Subscription, event: DomainEvent, now: float) -> bool:
    """只读判定：现在能不能执行（不写时间戳）。"""
    if sub.cooldown <= 0:
        return True
    last = _cooldown_seen.get(_cooldown_key(sub, event))
    return last is None or now - last >= sub.cooldown


def _cooldown_reserve(
    sub: Subscription, event: DomainEvent, now: float
) -> tuple[CooldownKey | None, object]:
    """执行前预占时间戳，返回 (key, 旧值) 供失败回滚。

    **先写后执行**而不是「成功后写」：NoneBot 并发处理同一事件时，
    两次投递都先判定通过再执行就会放过重复事件，预占能让第二次直接冷却。
    """
    if sub.cooldown <= 0:
        return None, _NO_PREVIOUS
    key = _cooldown_key(sub, event)
    previous = _cooldown_seen.get(key, _NO_PREVIOUS)
    _cooldown_seen[key] = now
    if len(_cooldown_seen) > _MAX_COOLDOWN_ENTRIES:
        for item, stamp in list(_cooldown_seen.items()):
            if now - stamp >= sub.cooldown:
                _cooldown_seen.pop(item, None)
    return key, previous


def _cooldown_rollback(key: CooldownKey, previous: object) -> None:
    """消费者失败时回滚预占：有旧时间戳就恢复，没有就删键（失败可重试）。"""
    if previous is _NO_PREVIOUS:
        _cooldown_seen.pop(key, None)
    else:
        _cooldown_seen[key] = float(previous)  # type: ignore[arg-type]


async def dispatch(
    event: DomainEvent,
    bot: Any = None,
    *,
    gate: GateCallable | None = None,
    now: float | None = None,
) -> DispatchReport:
    """把事件分发给订阅者：群级门控 → cooldown → 调用（异常隔离）。

    失败语义：单个消费者抛异常只影响它自己——计入 `report.failed`、记一条
    `logger.exception` 日志、回滚它预占的 cooldown，其它消费者照常执行。
    `src/plugins/events` 会把 `report.failed` 计入统计的 `errors` 指标。
    """
    report = DispatchReport(event_type=type(event).__name__)
    moment = time.monotonic() if now is None else now
    group_id = str(getattr(event, "group_id", ""))
    for sub in subscriptions(type(event)):
        report.matched += 1
        if sub.feature:
            allowed = await (gate or _default_gate)(group_id, sub.feature)
            if not allowed:
                report.gated += 1
                continue
        if not _cooldown_available(sub, event, moment):
            report.cooled += 1
            continue
        key: CooldownKey | None = None
        previous: object = _NO_PREVIOUS
        if sub.cooldown > 0:
            key, previous = _cooldown_reserve(sub, event, moment)
        try:
            await sub.handler(event, bot)
        except Exception:  # noqa: BLE001 - 单个消费者失败不影响其它消费者
            if key is not None:
                _cooldown_rollback(key, previous)
            report.failed += 1
            logger.exception("事件消费者失败：%s · %s", report.event_type, sub.name)
            continue
        report.delivered += 1
    return report


async def ingest(event: Any, bot: Any = None) -> DispatchReport | None:
    """入口：规范化 + 分发；不关心的事件返回 None。"""
    domain = normalize(event)
    if domain is None:
        return None
    report = await dispatch(domain, bot)
    logger.debug(
        "分发 %s：匹配 %d｜投递 %d｜门控 %d｜冷却 %d｜失败 %d",
        report.event_type, report.matched, report.delivered, report.gated, report.cooled, report.failed,
    )
    return report

