"""推送封装测试：去重、失败隔离、无 Bot 时安全返回、管理员解析。"""
from __future__ import annotations

from src.core import notify


class FakeBot:
    def __init__(self, *, fail: bool = False):
        self.self_id = "10001"
        self.fail = fail
        self.private: list[tuple[str, str]] = []
        self.groups: list[tuple[str, str]] = []

    async def send_private_msg(self, *, user_id, message, **kwargs):
        if self.fail:
            raise RuntimeError("boom")
        self.private.append((str(user_id), str(message)))

    async def send_group_msg(self, *, group_id, message, **kwargs):
        if self.fail:
            raise RuntimeError("boom")
        self.groups.append((str(group_id), str(message)))


async def test_send_private_dedups_and_counts():
    bot = FakeBot()
    assert await notify.send_private(["1", 1, "2"], "hi", bots=[bot]) == 2
    assert bot.private == [("1", "hi"), ("2", "hi")]


async def test_send_private_isolates_failures():
    assert await notify.send_private(["1"], "hi", bots=[FakeBot(fail=True)]) == 0


async def test_send_group_dedups_and_counts():
    bot = FakeBot()
    assert await notify.send_group(["100", "100", "200"], "公告", bots=[bot]) == 2
    assert bot.groups == [("100", "公告"), ("200", "公告")]


async def test_no_connected_bot_is_safe():
    assert await notify.send_private(["1"], "hi", bots=[]) == 0
    assert await notify.send_group(["100"], "hi", bots=[]) == 0


async def test_notify_admins(fresh_db):
    from src.core import permissions as perms

    await perms.add_admin("123456789")
    bot = FakeBot()
    assert await notify.notify_admins("简报", bots=[bot]) == 1
    assert bot.private == [("123456789", "简报")]
