"""日志脱敏工具测试：日志里只留「形状 + 指纹」。"""
from __future__ import annotations

from src.core import logsafe


def test_fingerprint_is_stable_and_shorter_than_body():
    assert logsafe.fingerprint("") == "-"
    assert logsafe.fingerprint("你好") == logsafe.fingerprint("你好")
    assert logsafe.fingerprint("你好") != logsafe.fingerprint("你好呀")
    assert len(logsafe.fingerprint("你好")) == 8
    assert len(logsafe.fingerprint("你好", length=4)) == 4
    assert logsafe.fingerprint("你好", length=0) != ""


def test_shape_reports_length_only():
    assert logsafe.shape("") == "len=0"
    assert logsafe.shape("abc") == "len=3"
    assert logsafe.shape("你好") == "len=2"
