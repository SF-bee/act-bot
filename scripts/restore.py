#!/usr/bin/env python3
"""从备份恢复数据库（覆盖当前库）。

用法：
    uv run python scripts/restore.py <备份文件> [--yes] [--force]

安全检查（三层）：
1. 先探测数据库是否仍被占用（-wal/-shm 残留或写锁）——bot 在跑时恢复会丢数据，默认拒绝；
2. 交互确认（输入 yes），脚本/CI 可用 --yes 跳过；
3. 当前库先另存为 *.pre-restore-*.bak 再覆盖（restore_database 内部完成）。
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
    parser.add_argument("--yes", action="store_true", help="跳过交互确认（脚本/CI 用）")
    parser.add_argument("--force", action="store_true", help="数据库疑似被占用时仍然恢复（危险）")
    args = parser.parse_args()

    from src.core import backup, db

    reason = db.database_in_use()
    if reason and not args.force:
        print(f"❌ 数据库疑似正在被使用：{reason}")
        print("   请先停止 bot（systemctl stop act-bot / 关闭 NSSM 服务 / docker compose down）后重试。")
        print("   若确认没有进程在使用，可加 --force 强制执行。")
        return 1

    if not args.yes:
        try:
            answer = input(f"将用 {args.backup_file} 覆盖当前数据库，输入 yes 继续：")
        except EOFError:
            answer = ""
        if answer.strip().lower() != "yes":
            print("已取消（未做任何修改）。")
            return 1

    target = backup.restore_database(args.backup_file)
    print(f"✅ 已恢复：{target}")
    print("提示：请重启 bot；旧库的同名 .pre-restore-*.bak 已就地保留，可手动回滚。")
    return 0


if __name__ == "__main__":
    sys.exit(main())