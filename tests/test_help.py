"""帮助菜单测试：usage 解析、按角色过滤、排序。"""
from __future__ import annotations

from src.core.help import ADMIN_ROLE, HelpEntry, build_entry, parse_usage, render_help


def test_parse_usage_splits_and_strips():
    raw = "\n/help — 看帮助\n\n/ping — 连通性\n  "
    assert parse_usage(raw) == ("/help — 看帮助", "/ping — 连通性")
    assert parse_usage(None) == ()
    assert parse_usage("") == ()


def test_build_entry_skips_empty_usage():
    assert build_entry(usage="") is None
    assert build_entry(usage=None) is None
    entry = build_entry(usage="/x", role="admin", order=5)
    assert entry == HelpEntry(lines=("/x",), role="admin", order=5)
    # order 非法时退回默认权重，不让配置错误炸掉帮助
    assert build_entry(usage="/x", order="abc").order == 100


def test_member_does_not_see_admin_section():
    entries = [
        HelpEntry(lines=("/ping — 连通性",), order=20),
        HelpEntry(lines=("/welcome — 预览（只读）",), role=ADMIN_ROLE, order=110),
    ]
    text = render_help(entries, is_admin=False, header="头")
    assert "/ping — 连通性" in text
    assert "/welcome — 预览（只读）" not in text
    assert "管理员命令" not in text


def test_admin_sees_both_sections():
    entries = [
        HelpEntry(lines=("/ping — 连通性",), order=20),
        HelpEntry(lines=("/welcome — 预览（只读）",), role=ADMIN_ROLE, order=110),
    ]
    text = render_help(entries, is_admin=True, header="头")
    assert "常用命令" in text and "管理员命令" in text
    assert text.index("/ping — 连通性") < text.index("/welcome — 预览（只读）")


def test_order_controls_sorting():
    entries = [
        HelpEntry(lines=("/late",), order=200),
        HelpEntry(lines=("/early",), order=1),
    ]
    text = render_help(entries, is_admin=False)
    assert text.index("/early") < text.index("/late")


def test_section_shows_placeholder_when_empty():
    text = render_help([], is_admin=True, header="头")
    assert text.count("（暂无）") == 2

