"""私聊管理群作用域解析测试。"""
from __future__ import annotations

import pytest

from src.core import scope


@pytest.fixture(autouse=True)
def _clean():
    scope.reset()
    yield
    scope.reset()


def test_group_scope_uses_event_group():
    result = scope.extract_scope(["list"], is_group=True, event_group_id="123456")
    assert result.group_id == "123456"
    assert result.tokens == ["list"]
    assert not result.error


def test_group_scope_strips_silent_flag():
    result = scope.extract_scope(["-s", "mute", "1"], is_group=True, event_group_id="123456")
    assert result.silent is True
    assert result.tokens == ["mute", "1"]


def test_group_scope_rejects_mismatched_g():
    result = scope.extract_scope(["-g", "999999", "list"], is_group=True, event_group_id="123456")
    assert result.error


def test_private_scope_uses_explicit_group():
    result = scope.extract_scope(["-g", "123456", "list"], is_group=False, actor_qq="7")
    assert result.group_id == "123456"
    assert result.tokens == ["list"]


def test_private_scope_requires_group_when_unbound():
    result = scope.extract_scope(["list"], is_group=False, actor_qq="7")
    assert result.group_id == ""
    assert "use" in result.error or "-g" in result.error


def test_private_scope_uses_binding():
    scope.bind("7", "888888")
    result = scope.extract_scope(["list"], is_group=False, actor_qq="7")
    assert result.group_id == "888888"


def test_bind_rejects_invalid_group():
    assert scope.bind("7", "abc") == ""
    assert scope.bound_group("7") == ""
    assert scope.bind("7", "12") == ""  # 少于 5 位


def test_clear_binding():
    scope.bind("7", "888888")
    scope.clear("7")
    assert scope.bound_group("7") == ""


def test_missing_group_argument_errors():
    result = scope.extract_scope(["-g"], is_group=False, actor_qq="7")
    assert result.error


def test_invalid_group_argument_errors():
    result = scope.extract_scope(["-g", "abc", "list"], is_group=False, actor_qq="7")
    assert result.error


async def test_binding_persists_across_restart(fresh_db):
    scope.reset()
    assert await scope.save("7", "888888") == "888888"
    scope.reset()  # 模拟重启：清空内存缓存
    assert scope.bound_group("7") == ""
    assert await scope.load_all() == 1
    assert scope.bound_group("7") == "888888"
    await scope.remove("7")
    assert scope.bound_group("7") == ""
    assert await scope.load_all() == 0


async def test_save_rejects_invalid_group(fresh_db):
    scope.reset()
    assert await scope.save("7", "abc") == ""
    assert scope.bound_group("7") == ""


async def test_remove_is_idempotent(fresh_db):
    scope.reset()
    await scope.remove("nobody")
    assert scope.bound_group("nobody") == ""
