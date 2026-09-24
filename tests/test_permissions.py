"""权限系统测试（管理员一律存数据库，代码零硬编码）。"""
from __future__ import annotations

import pytest


async def test_add_and_get_role(fresh_db):
    from src.core import permissions as perms

    assert await perms.get_role("10001") is None
    created = await perms.add_admin("10001", role=perms.ROLE_OWNER, note="首任")
    assert created is True
    assert await perms.get_role("10001") == perms.ROLE_OWNER
    assert await perms.has_role("10001", perms.ROLE_OWNER) is True
    assert await perms.has_role("10001", perms.ROLE_ADMIN) is True


async def test_admin_level_permissions(fresh_db):
    from src.core import permissions as perms

    await perms.add_admin("10002", role=perms.ROLE_ADMIN)
    assert await perms.has_role("10002", perms.ROLE_ADMIN) is True
    assert await perms.has_role("10002", perms.ROLE_OWNER) is False
    assert await perms.has_role("10003", perms.ROLE_ADMIN) is False


async def test_remove_and_transfer(fresh_db):
    from src.core import permissions as perms

    await perms.add_admin("10001", role=perms.ROLE_OWNER)
    await perms.add_admin("10002", role=perms.ROLE_ADMIN)
    await perms.transfer_owner("10002")
    assert await perms.get_role("10001") == perms.ROLE_ADMIN
    assert await perms.get_role("10002") == perms.ROLE_OWNER
    assert await perms.remove_admin("10001") is True
    assert await perms.remove_admin("10001") is False


async def test_qq_validation(fresh_db):
    from src.core import permissions as perms

    with pytest.raises(ValueError):
        await perms.add_admin("not-a-qq")
