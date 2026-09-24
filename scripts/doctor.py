#!/usr/bin/env python3
"""环境自检（macOS / Ubuntu / Windows 通用）。

用法：
    uv run python scripts/doctor.py

检查项：Python 版本、关键依赖、数据目录可写、时区数据、业务配置、数据库完整性。
退出码：0 = 全部通过（允许警告）；1 = 有失败项。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 仓库根进 sys.path

if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台 UTF-8 兜底
    sys.stdout.reconfigure(encoding="utf-8")

RESULTS: list[tuple[str, str, str]] = []


def check(name: str, fn) -> None:
    try:
        detail = fn()
        RESULTS.append(("OK", name, str(detail or "")))
    except Exception as exc:  # noqa: BLE001 - 自检工具：收集所有异常并展示
        RESULTS.append(("FAIL", name, f"{type(exc).__name__}: {exc}"))


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

    def _database() -> str:
        result = db.integrity_check()
        if result == "missing":
            return "未初始化（首次启动 bot 会自动创建；也可运行 bootstrap_admin.py）"
        if result != "ok":
            raise RuntimeError(f"完整性校验失败：{result}")
        return f"OK（{paths.db_path()}）"

    check("Python 版本", _python)
    check("关键依赖", _deps)
    check("数据目录可写", _data_dir)
    check("时区数据", _timezone)
    check("业务配置", _config)
    check("数据库", _database)

    print("\nACT Bot 环境自检\n" + "=" * 46)
    failed = 0
    for status, name, detail in RESULTS:
        icon = "✅" if status == "OK" else "❌"
        if status != "OK":
            failed += 1
        print(f"{icon} {name}：{detail}")
    print("=" * 46)
    print("结论：" + ("全部通过 🎉" if failed == 0 else f"{failed} 项失败，请按提示修复"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
