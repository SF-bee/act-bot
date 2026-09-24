"""备份 / 恢复 / 轮转测试（跨平台）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def _make_db(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
        conn.execute("INSERT INTO t(v) VALUES (?)", (value,))


def test_backup_and_restore_roundtrip(temp_data_dir):
    from src.core import backup, db

    target = db.db_path()
    _make_db(target, "original")

    backup_file = backup.backup_database()
    assert backup_file.exists()
    assert db.integrity_check(backup_file) == "ok"

    with sqlite3.connect(str(target)) as conn:
        conn.execute("DELETE FROM t")
    backup.restore_database(backup_file)
    with sqlite3.connect(str(target)) as conn:
        assert conn.execute("SELECT v FROM t").fetchone()[0] == "original"


def test_rotate_backups(temp_data_dir):
    from src.core import backup

    dest = temp_data_dir / "backups"
    dest.mkdir(parents=True, exist_ok=True)
    for day in range(1, 31):  # 2026-10：30 份
        (dest / f"act-202610{day:02d}-010000.db").write_bytes(b"x")
    for day in range(1, 11):  # 2026-11：10 份
        (dest / f"act-202611{day:02d}-010000.db").write_bytes(b"x")

    removed = backup.rotate_backups(dest, keep_daily_days=7, keep_monthly=2)
    remaining = sorted(p.name for p in dest.glob("act-*.db"))

    assert len(remaining) == 8  # 最近 7 份 + 月度补 1 份（10 月最新）
    assert "act-20261110-010000.db" in remaining
    assert "act-20261030-010000.db" in remaining  # 月度保留
    assert "act-20261001-010000.db" not in remaining
    assert len(removed) == 32
