"""备份 / 恢复（跨平台：只用 sqlite3 + 标准库）。

- 备份：sqlite3 在线备份 API（对运行中的库安全）+ 完整性校验 + 滚动保留；
- 恢复：校验备份 → 保存当前库 → 覆盖 → 清理 WAL 残留。

约定：**恢复前请先停止 bot**（避免恢复过程中仍有写入）。
"""
from __future__ import annotations

import datetime
import shutil
import sqlite3
from pathlib import Path

from . import db
from .paths import backups_dir, db_path, ensure_dir

BACKUP_PREFIX = "act-"
BACKUP_SUFFIX = ".db"


def _timestamp() -> str:
    # 文件名不含冒号等 Windows 保留字符
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def backup_database(
    dest_dir: Path | None = None,
    *,
    keep_daily_days: int = 30,
    keep_monthly: int = 6,
) -> Path:
    """执行一次数据库备份，返回备份文件路径。"""
    source = db_path()
    ensure_dir(source.parent)
    dest = ensure_dir(dest_dir or backups_dir())
    target = dest / f"{BACKUP_PREFIX}{_timestamp()}{BACKUP_SUFFIX}"
    with sqlite3.connect(str(source)) as src_conn, sqlite3.connect(str(target)) as dst_conn:
        src_conn.backup(dst_conn)
    result = db.integrity_check(target)
    if result != "ok":
        raise RuntimeError(f"备份完整性校验失败：{result}")
    rotate_backups(dest, keep_daily_days=keep_daily_days, keep_monthly=keep_monthly)
    return target


def rotate_backups(
    directory: Path,
    *,
    keep_daily_days: int = 30,
    keep_monthly: int = 6,
) -> list[Path]:
    """滚动清理备份：保留最近 N 天 + 最近 M 个月各一份。返回被删除的文件列表。"""
    files = sorted(directory.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"))
    if not files:
        return []
    if keep_daily_days <= 0 and keep_monthly <= 0:
        return []  # 两个都关 = 不做任何清理

    keep: set[Path] = set()
    if keep_daily_days > 0:
        keep.update(files[-keep_daily_days:])

    months: dict[str, Path] = {}
    for file in files:
        parts = file.stem.split("-")
        if len(parts) < 2 or len(parts[1]) < 6:
            keep.add(file)  # 文件名不符合约定 → 不主动删除
            continue
        months[parts[1][:6]] = file  # 同月保留最新（sorted 升序，后写覆盖）
    if keep_monthly > 0:
        for month in sorted(months)[-keep_monthly:]:
            keep.add(months[month])

    removed = [f for f in files if f not in keep]
    for file in removed:
        file.unlink()
    return removed


def restore_database(from_file: Path, *, safety_copy: bool = True) -> Path:
    """从备份文件恢复数据库（覆盖当前库）。恢复前请停止 bot。"""
    from_file = Path(from_file)
    if not from_file.is_file():
        raise FileNotFoundError(f"备份文件不存在：{from_file}")
    result = db.integrity_check(from_file)
    if result != "ok":
        raise RuntimeError(f"备份文件校验失败（{result}），已中止恢复")

    target = db_path()
    ensure_dir(target.parent)
    if target.exists() and safety_copy:
        safety = target.with_name(f"{target.name}.pre-restore-{_timestamp()}.bak")
        shutil.copy2(target, safety)
    shutil.copy2(from_file, target)
    # 旧库的 WAL/SHM 残留会让新库损坏 → 一并清理
    for suffix in ("-wal", "-shm"):
        residual = Path(f"{target}{suffix}")
        if residual.exists():
            residual.unlink()
    return target
