"""事件中枢测试：规范化、订阅、群级门控、cooldown、异常隔离。"""
from __future__ import annotations

import pytest
from nonebot.adapters.onebot.v11 import (
    GroupBanNoticeEvent,
    GroupDecreaseNoticeEvent,
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    GroupRecallNoticeEvent,
    Message,
)

from src.core import events
from src.core.events import (
    GroupMemberJoin,
    GroupMemberLeave,
    MemberMuted,
    MemberUnmuted,
    MessageReceived,
    MessageRecalled,
    dispatch,
    ingest,
    normalize,
    subscribe,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个测试用干净的订阅表，互不污染。"""
    events.clear_subscriptions()
    yield
    events.clear_subscriptions()


def _join(group_id: str = "200", user_id: str = "300") -> GroupMemberJoin:
    return GroupMemberJoin(group_id=group_id, user_id=user_id)


# ---------- 规范化 ----------

def test_normalize_group_increase():
    event = GroupIncreaseNoticeEvent(
        time=1, self_id=100, post_type="notice", notice_type="group_increase",
        sub_type="approve", group_id=200, user_id=300, operator_id=400,
    )
    assert normalize(event) == GroupMemberJoin(
        group_id="200", user_id="300", operator_id="400", sub_type="approve", raw=event
    )


def test_normalize_group_decrease():
    event = GroupDecreaseNoticeEvent(
        time=1, self_id=100, post_type="notice", notice_type="group_decrease",
        sub_type="kick", group_id=200, user_id=300, operator_id=400,
    )
    result = normalize(event)
    assert isinstance(result, GroupMemberLeave)
    assert (result.group_id, result.user_id, result.sub_type) == ("200", "300", "kick")


def test_normalize_recall_keeps_author_and_operator():
    event = GroupRecallNoticeEvent(
        time=1, self_id=100, post_type="notice", notice_type="group_recall",
        group_id=200, user_id=300, operator_id=400, message_id=55,
    )
    result = normalize(event)
    assert isinstance(result, MessageRecalled)
    assert (result.user_id, result.operator_id, result.message_id) == ("300", "400", "55")


def test_normalize_ban_and_lift():
    ban = GroupBanNoticeEvent(
        time=1, self_id=100, post_type="notice", notice_type="group_ban",
        sub_type="ban", group_id=200, user_id=300, operator_id=400, duration=600,
    )
    lift = GroupBanNoticeEvent(
        time=1, self_id=100, post_type="notice", notice_type="group_ban",
        sub_type="lift_ban", group_id=200, user_id=300, operator_id=400, duration=0,
    )
    muted = normalize(ban)
    unmuted = normalize(lift)
    assert isinstance(muted, MemberMuted) and muted.duration == 600
    assert isinstance(unmuted, MemberUnmuted)


def test_normalize_group_message():
    event = GroupMessageEvent(
        time=1, self_id=100, post_type="message", message_type="group", sub_type="normal",
        message_id=9, user_id=300, group_id=200, message=Message("hello 你好"),
        raw_message="hello 你好", font=0, sender={"user_id": 300, "nickname": "X"},
    )
    result = normalize(event)
    assert isinstance(result, MessageReceived)
    assert (result.group_id, result.user_id, result.text, result.is_group) == (
        "200", "300", "hello 你好", True,
    )


def test_normalize_unknown_event_returns_none():
    assert normalize(object()) is None


# ---------- 分发 ----------

async def test_dispatch_delivers_to_matching_subscriber():
    seen: list[tuple[str, str]] = []

    @subscribe(GroupMemberJoin, name="spy")
    async def _spy(event: GroupMemberJoin, bot) -> None:
        seen.append((event.group_id, event.user_id))

    report = await dispatch(_join())
    assert (report.matched, report.delivered) == (1, 1)
    assert seen == [("200", "300")]


async def test_dispatch_ignores_other_event_types():
    called: list[int] = []

    @subscribe(GroupMemberLeave, name="leave-spy")
    async def _spy(event: GroupMemberLeave, bot) -> None:
        called.append(1)

    report = await dispatch(_join())
    assert report.matched == 0 and called == []


async def test_feature_gate_blocks_disabled_feature():
    called: list[int] = []

    @subscribe(GroupMemberJoin, feature="welcome", name="gated")
    async def _gated(event: GroupMemberJoin, bot) -> None:
        called.append(1)

    async def closed(group_id: str, feature: str) -> bool:
        return False

    async def opened(group_id: str, feature: str) -> bool:
        return True

    blocked = await dispatch(_join(), gate=closed)
    assert blocked.gated == 1 and blocked.delivered == 0 and called == []

    allowed = await dispatch(_join(), gate=opened)
    assert allowed.delivered == 1 and called == [1]


async def test_cooldown_is_per_group_and_user():
    called: list[str] = []

    @subscribe(GroupMemberJoin, cooldown=60, name="cool")
    async def _cool(event: GroupMemberJoin, bot) -> None:
        called.append(event.user_id)

    first = await dispatch(_join(), now=100.0)
    repeat = await dispatch(_join(), now=101.0)
    other_user = await dispatch(_join(user_id="301"), now=101.0)
    later = await dispatch(_join(), now=200.0)

    assert (first.delivered, repeat.cooled, other_user.delivered, later.delivered) == (1, 1, 1, 1)
    assert called == ["300", "301", "300"]


async def test_consumer_failure_is_isolated():
    seen: list[str] = []

    @subscribe(GroupMemberJoin, name="boom")
    async def _boom(event: GroupMemberJoin, bot) -> None:
        raise RuntimeError("消费者炸了")

    @subscribe(GroupMemberJoin, name="ok")
    async def _ok(event: GroupMemberJoin, bot) -> None:
        seen.append("ok")

    report = await dispatch(_join())
    assert report.failed == 1 and report.delivered == 1
    assert seen == ["ok"]


async def test_ingest_normalizes_then_dispatches():
    seen: list[str] = []

    @subscribe(GroupMemberJoin, name="ingest-spy")
    async def _spy(event: GroupMemberJoin, bot) -> None:
        seen.append(event.user_id)

    event = GroupIncreaseNoticeEvent(
        time=1, self_id=100, post_type="notice", notice_type="group_increase",
        sub_type="approve", group_id=200, user_id=300, operator_id=400,
    )
    assert await ingest(event) is not None
    assert await ingest(object()) is None
    assert seen == ["300"]

