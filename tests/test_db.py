"""数据库与迁移测试。"""
from __future__ import annotations

import sqlite3

from sqlalchemy import text


async def test_migrations_apply_and_idempotent(temp_data_dir):
    from src.core import db

    version = db.apply_migrations()
    assert version >= 1
    assert db.apply_migrations() == version  # 幂等

    target = db.db_path()
    assert target.exists()
    with sqlite3.connect(str(target)) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    expected = {
        "meta",
        "admins",
        "groups",
        "departments",
        "events",
        "event_signups",
        "announcements",
        "archive_items",
        "settings",
        "audit_log",
    }
    assert expected <= tables


async def test_session_roundtrip(fresh_db):
    async with fresh_db.get_session() as session:
        await session.execute(
            text("INSERT INTO meta(key, value, updated_at) VALUES ('k', 'v', '')")
        )
        await session.commit()
        value = (
            await session.execute(text("SELECT value FROM meta WHERE key = 'k'"))
        ).scalar_one()
        assert value == "v"


async def test_integrity_check(fresh_db):
    assert fresh_db.integrity_check() == "ok"
