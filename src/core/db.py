"""数据库层：SQLite + SQLAlchemy 2.x（async）+ 版本化 SQL 迁移。

跨平台约束：仅使用 sqlite3 / SQLAlchemy / aiosqlite；不使用平台特定功能。
结构基线是 ``src/core/migrations/*.sql``（模型文件仅用于查询，需与其保持同步）。
"""
from __future__ import annotations

import sqlite3
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


def utc_now() -> str:
    """统一的 UTC 时间字符串（ISO-8601，秒级）。

    时间戳的唯一来源：permissions / groups / audit 等模块都从这里取，
    保证各表 ``created_at`` 格式一致（便于比较与交接导出）。
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- 同步工具（迁移 / 完整性检查 / 备份脚本使用） ----------


def apply_migrations(path: Path | None = None) -> int:
    """按文件名顺序应用 ``migrations/*.sql``；用 ``PRAGMA user_version`` 记录版本。

    返回应用后的数据库版本号（幂等：可重复调用）。
    """
    target = path or db_path()
    ensure_dir(target.parent)
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
