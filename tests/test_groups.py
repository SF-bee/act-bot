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


async def test_broken_features_json_falls_back_to_default(fresh_db):
    await groups.set_feature("998", "welcome", False)
    async with db.get_session() as session:
        row = (await session.execute(select(Group).where(Group.group_id == "998"))).scalar_one()
        row.features = "not-a-json"
        await session.commit()
    # 坏数据当空字典：回退到 default，而不是抛异常
    assert await groups.feature_enabled("998", "welcome") is True

