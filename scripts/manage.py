#!/usr/bin/env python3
"""离线管理工具（bot 不启动也能用）。

用法：
    uv run python scripts/manage.py admins list
    uv run python scripts/manage.py admins add <QQ> [--role admin|owner] [--note 备注]
    uv run python scripts/manage.py admins remove <QQ>
    uv run python scripts/manage.py admins transfer <QQ>     # 转让 owner

说明：直接读写数据库；管理员信息只存在于数据库，代码中不出现任何 QQ 号。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


async def _run(coro):
    from src.core import db

    await db.init_db()
    try:
        return await coro
    finally:
        await db.dispose_engine()


async def _list() -> int:
    from src.core import permissions as perms

    admins = await perms.list_admins()
    if not admins:
        print("（暂无管理员；首次部署请运行 bootstrap_admin.py）")
        return 0
    for admin in admins:
        suffix = f"  # {admin.note}" if admin.note else ""
        print(f"{admin.qq}\t{admin.role}{suffix}")
    return 0


async def _add(qq: str, role: str, note: str) -> int:
    from src.core import permissions as perms

    created = await perms.add_admin(qq, role=role, note=note, created_by="manage.py")
    print(f"✅ {qq} {'已添加' if created else '已更新'}：{role}")
    return 0


async def _remove(qq: str) -> int:
    from src.core import permissions as perms

    removed = await perms.remove_admin(qq)
    print(f"✅ 已移除：{qq}" if removed else f"⚠️ 不存在：{qq}")
    return 0 if removed else 1


async def _transfer(qq: str) -> int:
    from src.core import permissions as perms

    await perms.transfer_owner(qq, created_by="manage.py")
    print(f"✅ 已将 owner 转让给：{qq}（旧 owner 已降为 admin）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ACT Bot 离线管理工具")
    sub = parser.add_subparsers(dest="group", required=True)

    admins = sub.add_parser("admins", help="管理员管理")
    admins_sub = admins.add_subparsers(dest="action", required=True)
    admins_sub.add_parser("list", help="列出管理员")
    add_p = admins_sub.add_parser("add", help="添加/更新管理员")
    add_p.add_argument("qq")
    add_p.add_argument("--role", choices=["admin", "owner"], default="admin")
    add_p.add_argument("--note", default="")
    rm_p = admins_sub.add_parser("remove", help="移除管理员")
    rm_p.add_argument("qq")
    tr_p = admins_sub.add_parser("transfer", help="转让 owner")
    tr_p.add_argument("qq")

    args = parser.parse_args()

    if args.group == "admins":
        if args.action == "list":
            return asyncio.run(_run(_list()))
        if args.action == "add":
            return asyncio.run(_run(_add(args.qq, args.role, args.note)))
        if args.action == "remove":
            return asyncio.run(_run(_remove(args.qq)))
        if args.action == "transfer":
            return asyncio.run(_run(_transfer(args.qq)))
    return 2


if __name__ == "__main__":
    sys.exit(main())
