"""群级设置测试：features JSON 读写与 /config 参数解析。"""
from __future__ import annotations

import json

from sqlalchemy import select

from src.core import db, groups
from src.models.tables import Group


def test_parse_feature_command():
    assert groups.parse_feature_command("/config") == ("", "")
    assert groups.parse_feature_command("/config welcome") == ("welcome", "")
    assert groups.parse_feature_command("/config welcome on") == ("welcome", "on")
    assert groups.parse_feature_command("/config  Welcome  OFF ") == ("welcome", "off")
    assert groups.parse_feature_command("/config welcome maybe") == ("welcome", "unknown")


async def test_default_then_set_then_read(fresh_db):
    assert await groups.feature_enabled("999", "welcome") is True
    assert await groups.feature_enabled("999", "chat", default=False) is False

    await groups.set_feature("999", "chat", True, group_name="测试群")
    assert await groups.feature_enabled("999", "chat", default=False) is True

    row = await groups.get_group("999")
    assert row is not None
    assert row.name == "测试群"
    assert json.loads(row.features)["chat"] is True


async def test_list_groups_and_group_ids(fresh_db):
    await groups.set_feature("200", "stats", True, group_name="乙群")
    await groups.set_feature("100", "stats", True, group_name="甲群")
    assert await groups.group_ids() == ["100", "200"]
    assert [row.name for row in await groups.list_groups()] == ["甲群", "乙群"]


async def test_upsert_group_keeps_features_and_updates_name(fresh_db):
    await groups.set_feature("300", "chat", True, group_name="旧名")
    await groups.upsert_group("300", "新名")
    row = await groups.get_group("300")
    assert row is not None
    assert row.name == "新名"
    assert json.loads(row.features)["chat"] is True


async def test_sync_groups_registers_roster(fresh_db):
    class FakeBot:
        async def get_group_list(self):
            return [
                {"group_id": 111, "group_name": "一群"},
                {"group_id": "222", "group_name": "二群"},
                {"group_name": "没有群号"},
            ]

    assert await groups.sync_from_bot(FakeBot()) == 2
    assert await groups.group_ids() == ["111", "222"]
    assert [row.name for row in await groups.list_groups()] == ["一群", "二群"]


async def test_sync_from_bot_swallows_errors(fresh_db):
    class BrokenBot:
        async def get_group_list(self):
            raise RuntimeError("boom")

    assert await groups.sync_from_bot(BrokenBot()) == 0


async def test_broken_features_json_falls_back_to_default(fresh_db):
    await groups.set_feature("998", "welcome", False)
    async with db.get_session() as session:
        row = (await session.execute(select(Group).where(Group.group_id == "998"))).scalar_one()
        row.features = "not-a-json"
        await session.commit()
    # 坏数据当空字典：回退到 default，而不是抛异常
    assert await groups.feature_enabled("998", "welcome") is True

