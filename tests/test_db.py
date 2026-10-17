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


async def test_admins_table_has_at_most_one_owner(fresh_db):
    """迁移 008 的部分唯一索引：第二行 owner 必须被数据库拒绝。"""
    import pytest
    from sqlalchemy.exc import IntegrityError

    async with fresh_db.get_session() as session:
        await session.execute(
            text("INSERT INTO admins(qq, role) VALUES ('11111', 'owner')")
        )
        with pytest.raises(IntegrityError):
            # 第二条 INSERT 在 autoflush 时就会撞上部分唯一索引
            await session.execute(
                text("INSERT INTO admins(qq, role) VALUES ('22222', 'owner')")
            )
            await session.commit()


async def test_migration_008_dedupes_legacy_owners(temp_data_dir, monkeypatch, tmp_path):
    """历史遗留多个 owner 时，008 保留 id 最大者、其余降 admin，并建立唯一索引。"""
    from src.core import db

    real_dir = db.MIGRATIONS_DIR
    legacy = tmp_path / "legacy-migrations"
    legacy.mkdir()
    for migration in sorted(real_dir.glob("*.sql")):
        if int(migration.name.split("_", 1)[0]) <= 7:
            (legacy / migration.name).write_text(
                migration.read_text(encoding="utf-8"), encoding="utf-8"
            )

    monkeypatch.setattr(db, "MIGRATIONS_DIR", legacy)
    assert db.apply_migrations() == 7

    target = db.db_path()
    with sqlite3.connect(str(target)) as conn:
        conn.execute("INSERT INTO admins(qq, role, created_by) VALUES ('11111', 'owner', 'legacy')")
        conn.execute("INSERT INTO admins(qq, role, created_by) VALUES ('22222', 'owner', 'legacy')")
        conn.commit()

    monkeypatch.setattr(db, "MIGRATIONS_DIR", real_dir)
    assert db.apply_migrations() == 9

    with sqlite3.connect(str(target)) as conn:
        rows = conn.execute("SELECT qq, role FROM admins ORDER BY id").fetchall()
        indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert rows == [("11111", "admin"), ("22222", "owner")]
    assert "uq_admins_single_owner" in indexes


def test_migration_lock_times_out(temp_data_dir, monkeypatch):
    import pytest

    from src.core import db

    target = db.db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = db.migration_lock_path(target)
    lock.write_text("other-process 1", encoding="utf-8")
    monkeypatch.setattr(db, "MIGRATION_LOCK_TIMEOUT", 0.2)
    with pytest.raises(RuntimeError, match="迁移锁被占用"):
        db.apply_migrations()
    assert lock.exists(), "别人的锁不能被我们顺手删掉"


def test_migration_lock_reclaims_stale_lock(temp_data_dir):
    import os
    import time

    from src.core import db

    target = db.db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = db.migration_lock_path(target)
    lock.write_text("crashed-process 1", encoding="utf-8")
    old = time.time() - db.MIGRATION_LOCK_STALE - 10
    os.utime(lock, (old, old))

    assert db.apply_migrations() >= 8
    assert not lock.exists(), "迁移结束后必须释放锁"


def test_database_in_use_detects_open_connection(temp_data_dir):
    import sqlite3

    from src.core import db

    db.apply_migrations()
    target = db.db_path()
    assert db.database_in_use() == ""

    conn = sqlite3.connect(str(target))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS _probe(x INTEGER)")
        conn.execute("INSERT INTO _probe(x) VALUES (1)")
        conn.commit()
        assert db.database_in_use() != "", "有连接持有 WAL 时应检测到占用"
    finally:
        conn.close()
    assert db.database_in_use() == "", "连接关闭后 WAL/SHM 应被清理"


async def test_integrity_check(fresh_db):
    assert fresh_db.integrity_check() == "ok"
