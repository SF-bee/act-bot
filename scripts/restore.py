#!/usr/bin/env python3
"""从备份恢复数据库（覆盖当前库）。

用法：
    uv run python scripts/restore.py <备份文件>

注意：恢复前请先停止 bot；当前库会先被另存为 *.pre-restore-*.bak。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="从备份恢复 ACT Bot 数据库")
    parser.add_argument("backup_file", type=Path, help="备份文件路径（.db）")
    args = parser.parse_args()

    from src.core import backup

    target = backup.restore_database(args.backup_file)
    print(f"✅ 已恢复：{target}")
    print("提示：如果 bot 正在运行，请重启它以重新连接数据库。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
