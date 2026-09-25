"""功能注册表测试。"""
from __future__ import annotations

from src.core import features


def test_lookup_is_case_insensitive():
    assert features.get("welcome") is not None
    assert features.get("WELCOME") is not None
    assert features.get("no-such-feature") is None


def test_defaults():
    assert features.default_of(features.FEATURE_WELCOME) is True
    assert features.default_of(features.FEATURE_CHAT) is False, "聊天互动默认关闭，需管理员显式打开"
    assert features.default_of("unknown") is True
    assert features.default_of("unknown", fallback=False) is False


def test_registry_is_consistent():
    names = features.names()
    assert len(names) == len(set(names))
    assert set(names) == {item.name for item in features.all_features()}
    for item in features.all_features():
        assert item.label and item.description

