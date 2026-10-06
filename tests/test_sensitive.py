"""内置敏感词匹配测试：归一化、trie、跳过干扰、白名单、最短长度。"""
from __future__ import annotations

from src.core import sensitive


def test_normalize_fullwidth_case_and_control():
    assert sensitive.normalize("ＡＢＣ１２３") == "abc123"
    assert sensitive.normalize("A\u200bB") == "ab"
    assert sensitive.normalize("") == ""


def test_basic_match():
    matcher = sensitive.SensitiveMatcher(["刷单", "赌博"])
    assert matcher.find("诚招兼职刷单") == ["刷单"]
    assert matcher.find("正常聊天") == []


def test_case_insensitive_english():
    matcher = sensitive.SensitiveMatcher(["fuck"])
    assert matcher.find("FUCK") == ["fuck"]


def test_skip_separators():
    matcher = sensitive.SensitiveMatcher(["加群"])
    assert matcher.find("加 群", skip=False) == []
    assert matcher.find("加 群", skip=True) == ["加群"]


def test_allow_list_suppresses_match_inside_allow_word():
    matcher = sensitive.SensitiveMatcher(["赌博"], allow=["禁止赌博"])
    assert matcher.find("禁止赌博") == []
    assert matcher.find("聚众赌博") == ["赌博"]


def test_min_length_filters_single_char():
    matcher = sensitive.SensitiveMatcher(["坏"])
    assert matcher.find("真坏", min_length=2) == []
    assert matcher.find("真坏", min_length=1) == ["坏"]


def test_overlapping_words_all_returned():
    matcher = sensitive.SensitiveMatcher(["办证", "办证刻章"])
    assert set(matcher.find("办证刻章")) == {"办证", "办证刻章"}


def test_load_words_skips_comments(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("# comment\n刷单\n\n赌博\n", encoding="utf-8")
    words = sensitive.load_words(path)
    assert words == ["刷单", "赌博"]
    assert sensitive.SensitiveMatcher(words).word_count == 2


def test_skip_inserted_chars_and_repeat():
    matcher = sensitive.SensitiveMatcher(["刷单"])
    assert matcher.find("刷 单", skip=True) == ["刷单"]
    assert matcher.find("刷1单", skip=True) == ["刷单"]
    assert matcher.find("刷a单", skip=True) == ["刷单"]
    assert matcher.find("刷刷单", skip=True) == ["刷单"]
    assert matcher.find("刷1单", skip=False) == []


def test_skip_does_not_skip_chinese():
    matcher = sensitive.SensitiveMatcher(["刷单"])
    assert matcher.find("刷中单", skip=True) == []


def test_traditional_conversion():
    matcher = sensitive.SensitiveMatcher(["刷单"])
    assert matcher.find("刷單", t2s={"單": "单"}) == ["刷单"]
    assert matcher.find("刷單") == []


def test_load_t2s(tmp_path):
    path = tmp_path / "t2s.txt"
    path.write_text("# c\n單 单\n後 后\n", encoding="utf-8")
    assert sensitive.load_t2s(path) == {"單": "单", "後": "后"}


def test_find_patterns():
    hits = sensitive.find_patterns("看 https://spam.example.com/x 电话13800138000 加群123456789")
    kinds = {kind for kind, _ in hits}
    assert "url" in kinds and "phone" in kinds


def test_find_pinyin_matches_ascii_run():
    old = sensitive._pinyin_matcher
    sensitive._pinyin_matcher = sensitive.SensitiveMatcher(["shuadan"])
    try:
        assert sensitive.find_pinyin("这是shuadan广告") == ["shuadan"]
        assert sensitive.find_pinyin("shua dan") == ["shuadan"]
        assert sensitive.find_pinyin("normal english here") == []
    finally:
        sensitive._pinyin_matcher = old
