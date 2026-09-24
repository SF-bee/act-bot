#!/usr/bin/env python3
"""首次部署：写入 owner 管理员。

用法：
    uv run python scripts/bootstrap_admin.py                    # 读取 .env 的 ACTBOT_BOOTSTRAP_ADMIN_QQ
    uv run python scripts/bootstrap_admin.py --qq 123456789

说明：仅用于"冷启动"第一个管理员；已存在 owner 时会拒绝（防误操作），
      换届请改用 ``scripts/manage.py admins transfer``。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


async def _bootstrap(qq: str, force: bool) -> int:
    from src.core import db
    from src.core import permissions as perms

    await db.init_db()
    try:
        owners = [a for a in await perms.list_admins() if a.role == perms.ROLE_OWNER]
        if owners:
            if not force:
                print("❌ 已存在 owner：" + "、".join(a.qq for a in owners))
                print("   换届请使用：uv run python scripts/manage.py admins transfer <新QQ>")
                print("   （如确实要追加管理员，可加 --force 以 admin 身份添加）")
                return 1
            created = await perms.add_admin(
                qq, role=perms.ROLE_ADMIN, note="bootstrap --force", created_by="bootstrap"
            )
            print(f"✅ {qq} {'已添加' if created else '已更新'}为 admin")
            return 0
        await perms.add_admin(qq, role=perms.ROLE_OWNER, note="bootstrap", created_by="bootstrap")
        print(f"✅ 已写入 owner：{qq}")
        return 0
    finally:
        await db.dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(description="写入 ACT Bot 的初始 owner 管理员")
    parser.add_argument("--qq", default=None, help="管理员 QQ（默认读取 .env 的 ACTBOT_BOOTSTRAP_ADMIN_QQ）")
    parser.add_argument("--force", action="store_true", help="已存在 owner 时仍以 admin 身份添加")
    args = parser.parse_args()

    from src.core.config import get_settings

    qq = (args.qq or get_settings().bootstrap_admin_qq or "").strip()
    if not qq:
        print("❌ 未提供管理员 QQ：请设置 .env 的 ACTBOT_BOOTSTRAP_ADMIN_QQ，或使用 --qq 参数")
        return 1
    return asyncio.run(_bootstrap(qq, args.force))


if __name__ == "__main__":
    sys.exit(main())
