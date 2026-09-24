#!/usr/bin/env python3
"""执行一次数据库备份（跨平台）。

用法：
    uv run python scripts/backup.py [--dest 目录]

说明：bot 内置调度器每日也会调用同一函数；本脚本用于手动备份。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="备份 ACT Bot 数据库")
    parser.add_argument("--dest", type=Path, default=None, help="备份输出目录（默认 data/backups）")
    args = parser.parse_args()

    from src.core import backup

    target = backup.backup_database(dest_dir=args.dest)
    print(f"✅ 备份完成：{target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
