"""restore.py 的安全检查（子进程运行，避免干扰当前测试引擎）。"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _prepare(temp_data_dir):
    """建一个已迁移的库，再复制一份当备份文件。"""
    from src.core import db

    db.apply_migrations()
    source = db.db_path()
    backup_file = temp_data_dir.parent / "act-backup.db"
    shutil.copy2(source, backup_file)
    return source, backup_file


def _run(backup_file, *extra, stdin=None):
    env = {**os.environ}
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "restore.py"), str(backup_file), *extra],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
        input=stdin,
    )


def test_restore_cancels_without_confirmation(temp_data_dir):
    source, backup_file = _prepare(temp_data_dir)
    conn = sqlite3.connect(str(source))
    try:
        before = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()  # 必须真的关闭：WAL 库有连接就会留下 -wal/-shm，restore 会判定为占用

    result = _run(backup_file)  # stdin 为空 → 视为取消
    assert result.returncode == 1
    assert "已取消" in result.stdout
    with sqlite3.connect(str(source)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == before


def test_restore_with_yes(temp_data_dir):
    source, backup_file = _prepare(temp_data_dir)
    result = _run(backup_file, "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "已恢复" in result.stdout
    assert source.exists()