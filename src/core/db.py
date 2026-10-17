"""数据库层：SQLite + SQLAlchemy 2.x（async）+ 版本化 SQL 迁移。

跨平台约束：仅使用 sqlite3 / SQLAlchemy / aiosqlite；不使用平台特定功能。
结构基线是 ``src/core/migrations/*.sql``（模型文件仅用于查询，需与其保持同步）。
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .paths import db_path, ensure_dir

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# 迁移锁：跨进程保护 apply_migrations（bot / doctor / manage.py / bootstrap 可能同时跑）。
# 用 O_CREAT|O_EXCL 锁文件而不是 BEGIN IMMEDIATE：executescript 会隐式提交，
# SQLite 事务包不住整批迁移；锁文件跨平台、无新依赖、崩溃后靠 mtime 判过期。
MIGRATION_LOCK_SUFFIX = ".migrate.lock"
MIGRATION_LOCK_TIMEOUT = 10.0  # 等锁最多多少秒
MIGRATION_LOCK_STALE = 600.0  # 锁文件超过多少秒视为崩溃遗留


def utc_now() -> str:
    """统一的 UTC 时间字符串（ISO-8601，秒级）。

    时间戳的唯一来源：permissions / groups / audit 等模块都从这里取，
    保证各表 ``created_at`` 格式一致（便于比较与交接导出）。
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- 同步工具（迁移 / 完整性检查 / 备份脚本使用） ----------


def migration_lock_path(target: Path | None = None) -> Path:
    """迁移锁文件路径（和数据库同目录，备份/迁移时一眼可见）。"""
    return Path(str(target or db_path()) + MIGRATION_LOCK_SUFFIX)


@contextlib.contextmanager
def _migration_lock(
    target: Path,
    *,
    timeout: float | None = None,
    stale: float | None = None,
):
    """跨进程互斥执行迁移：拿不到锁就等，超时抛 RuntimeError，崩溃遗留的锁自动清理。"""
    timeout = MIGRATION_LOCK_TIMEOUT if timeout is None else timeout
    stale = MIGRATION_LOCK_STALE if stale is None else stale
    lock = migration_lock_path(target)
    ensure_dir(lock.parent)
    deadline = time.monotonic() + timeout
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except FileNotFoundError:  # 刚被别人删掉 → 立刻重试
                continue
            if age > stale:
                with contextlib.suppress(FileNotFoundError):
                    lock.unlink()
                continue
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"迁移锁被占用超过 {timeout:.0f}s：{lock}"
                    "（若确认没有进程在初始化数据库，删除该文件后重试）"
                )
            time.sleep(0.1)
    try:
        os.write(fd, f"{os.getpid()} {time.time():.0f}".encode("utf-8"))
        yield lock
    finally:
        os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            lock.unlink()


def database_in_use(path: Path | None = None, *, timeout: float = 0.5) -> str:
    """猜测数据库是否正被其它进程使用；返回原因（空串 = 看起来空闲）。

    两个信号，都不完美，用于 restore / doctor 的「先停 bot」提醒：
    1. -wal / -shm 残留：正常关闭时 SQLite 会删除，存在通常说明还有连接；
    2. BEGIN IMMEDIATE 拿不到写锁：说明此刻有活跃写入。
    """
    target = path or db_path()
    if not target.exists():
        return ""
    if Path(str(target) + "-wal").exists() or Path(str(target) + "-shm").exists():
        return "存在 -wal/-shm 残留（通常代表仍有进程连着数据库）"
    conn = sqlite3.connect(str(target), timeout=timeout)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()
    except sqlite3.OperationalError as exc:
        return f"数据库被锁：{exc}"
    finally:
        conn.close()
    return ""


def apply_migrations(path: Path | None = None) -> int:
    """按文件名顺序应用 migrations/*.sql；用 PRAGMA user_version 记录版本。

    迁移全程持有跨进程迁移锁（bot 启动 / doctor / manage.py / bootstrap 并发时不会互相踩踏）。
    返回应用后的数据库版本号（幂等：可重复调用）。
    """
    target = path or db_path()
    ensure_dir(target.parent)
    with _migration_lock(target):
        conn = sqlite3.connect(str(target))
        try:
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                try:
                    version = int(migration.name.split("_", 1)[0])
                except ValueError:
                    continue
                if version <= current:
                    continue
                conn.executescript(migration.read_text(encoding="utf-8"))
                conn.execute(f"PRAGMA user_version = {version}")
                conn.commit()
                current = version
            return current
        finally:
            conn.close()


def integrity_check(path: Path | None = None) -> str:
    """返回 ``"ok"`` 或错误描述；文件不存在返回 ``"missing"``。"""
    target = path or db_path()
    if not target.exists():
        return "missing"
    conn = sqlite3.connect(str(target))
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "unknown"
    finally:
        conn.close()


# ---------- 异步引擎（运行时使用） ----------

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _make_engine(path: Path) -> AsyncEngine:
    url = URL.create("sqlite+aiosqlite", database=str(path))
    engine = create_async_engine(url, echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record) -> None:  # pragma: no cover - 连接参数
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


async def init_db(path: Path | None = None) -> Path:
    """初始化数据库：先跑迁移，再创建异步引擎。返回数据库文件路径。"""
    global _engine, _session_factory
    target = path or db_path()
    apply_migrations(target)
    if _engine is not None:
        await _engine.dispose()
    _engine = _make_engine(target)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return target


async def dispose_engine() -> None:
    """关闭引擎（进程退出 / 测试清理时调用）。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """获取数据库会话（须先调用 :func:`init_db`，bot 启动钩子会自动处理）。"""
    if _session_factory is None:
        raise RuntimeError("数据库尚未初始化：请先调用 db.init_db()（bot 启动钩子会自动处理）")
    async with _session_factory() as session:
        yield session
