#!/usr/bin/env python3
"""环境自检（macOS / Ubuntu / Windows 通用）。

用法：
    uv run python scripts/doctor.py

检查项：Python 版本、关键依赖、数据目录可写、时区数据、业务配置、数据库完整性、
        签到 ID 格式。
退出码：0 = 全部通过（允许警告）；1 = 有失败项。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 仓库根进 sys.path

if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台 UTF-8 兜底
    sys.stdout.reconfigure(encoding="utf-8")

RESULTS: list[tuple[str, str, str]] = []


def check(name: str, fn) -> None:
    """跑一项检查；fn 可返回 ("WARN", detail) 表示「不算失败但需留意」。"""
    try:
        detail = fn()
    except Exception as exc:  # noqa: BLE001 - 自检工具：收集所有异常并展示
        RESULTS.append(("FAIL", name, f"{type(exc).__name__}: {exc}"))
        return
    if isinstance(detail, tuple) and len(detail) == 2 and detail[0] == "WARN":
        RESULTS.append(("WARN", name, str(detail[1] or "")))
    else:
        RESULTS.append(("OK", name, str(detail or "")))


def main() -> int:
    from src.core import config, db, paths

    def _python() -> str:
        if sys.version_info < (3, 10):
            raise RuntimeError(f"Python 版本过低：{sys.version.split()[0]}（需要 >= 3.10）")
        return sys.version.split()[0]

    def _deps() -> str:
        import aiosqlite  # noqa: F401
        import apscheduler  # noqa: F401
        import nonebot
        import sqlalchemy

        return f"nonebot {getattr(nonebot, '__version__', '?')} / sqlalchemy {sqlalchemy.__version__}"

    def _data_dir() -> str:
        directory = paths.ensure_dir(paths.get_data_dir())
        probe = directory / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return str(directory)

    def _timezone() -> str:
        import zoneinfo

        settings = config.get_settings()
        zoneinfo.ZoneInfo(settings.timezone)
        return settings.timezone

    def _config() -> str:
        settings = config.get_settings()
        enabled = sum(1 for value in settings.features.values() if value)
        return f"备份 {settings.backup_daily_at}｜功能开关 {enabled}/{len(settings.features)}"

    def _db_usage():
        """数据库是否可能仍被占用（bot 在跑时恢复/迁移都可能出问题）。"""
        lock = db.migration_lock_path()
        if lock.exists():
            return (
                "WARN",
                f"迁移锁文件存在：{lock}（可能另一个进程正在初始化数据库；"
                "确认没有进程后可删除，10 分钟未更新的旧锁会自动回收）",
            )
        reason = db.database_in_use()
        if reason:
            return ("WARN", f"{reason}；若 bot 正在运行，迁移/恢复前请先停 bot")
        return "未发现 -wal/-shm 残留或写锁"

    def _database() -> str:
        result = db.integrity_check()
        if result == "missing":
            return "未初始化（首次启动 bot 会自动创建；也可运行 bootstrap_admin.py）"
        if result != "ok":
            raise RuntimeError(f"完整性校验失败：{result}")
        return f"OK（{paths.db_path()}）"

    def _id_formats():
        """历史数据里的非法 QQ/群号（新代码会在入口拒绝，但旧行仍可能残留）。"""
        if db.integrity_check() == "missing":
            return "未初始化，跳过"
        target = paths.db_path()
        with sqlite3.connect(str(target)) as conn:
            count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM checkins WHERE"
                    " group_id NOT GLOB '[0-9]*' OR LENGTH(group_id) < 5"
                    " OR user_id NOT GLOB '[0-9]*' OR LENGTH(user_id) < 5"
                ).fetchone()[0]
                or 0
            )
        if count:
            return (
                "WARN",
                f"checkins 有 {count} 行不是纯数字 QQ/群号（测试遗留？新代码会拒绝写入）",
            )
        return "checkins 全部是纯数字"

    check("Python 版本", _python)
    check("关键依赖", _deps)
    check("数据目录可写", _data_dir)
    check("时区数据", _timezone)
    check("业务配置", _config)
    check("数据库", _database)
    check("数据库占用", _db_usage)
    check("签到 ID 格式", _id_formats)

    print("\nACT Bot 环境自检\n" + "=" * 46)
    icons = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}
    failed = sum(1 for status, _, _ in RESULTS if status == "FAIL")
    warned = sum(1 for status, _, _ in RESULTS if status == "WARN")
    for status, name, detail in RESULTS:
        print(f"{icons.get(status, '❌')} {name}：{detail}")
    print("=" * 46)
    if failed:
        print(f"结论：{failed} 项失败，请按提示修复")
    elif warned:
        print(f"结论：全部通过，但有 {warned} 项警告 ⚠️")
    else:
        print("结论：全部通过 🎉")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
