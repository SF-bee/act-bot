"""群风控测试：规则匹配、刷屏/复读、警告升级、命令解析、DB 存取、配置校验。"""
from __future__ import annotations

import pytest

from src.core import config, moderation
from src.core.config import ConfigError


def _policy(**kwargs) -> moderation.Policy:
    base = dict(
        cooldown=0.0,
        warn_before_mute=3,
        strike_window=600.0,
        flood_window=8.0,
        flood_max=100,
        flood_action=moderation.ACTION_MUTE,
        duplicate_window=30.0,
        duplicate_max=100,
        duplicate_action=moderation.ACTION_WARN,
        mention_all_action=moderation.ACTION_WARN,
        default_mute_seconds=600,
        max_mute_seconds=2592000,
    )
    base.update(kwargs)
    return moderation.Policy(**base)


def _rule(**kwargs) -> moderation.Rule:
    base = dict(id=1, kind="keyword", pattern="违禁", action="warn", recall=True, note="违禁词")
    base.update(kwargs)
    return moderation.Rule(**base)


# ---------- 纯逻辑 ----------


def test_fingerprint_text_and_image():
    assert moderation.fingerprint(" Hello   World ") == "helloworld"
    assert moderation.fingerprint("", ["a", "b"]) == "a|b"
    assert moderation.fingerprint(" ", []) == ""


def test_match_rules_keyword_and_regex():
    rules = [
        _rule(id=1, kind="keyword", pattern="加群"),
        _rule(id=2, kind="regex", pattern=r"1[3-9]\d{9}"),
    ]
    matched = moderation.match_rules(rules, "加群 13800138000")
    assert {rule.id for rule in matched} == {1, 2}


def test_match_rules_skips_invalid_regex():
    rules = [_rule(id=3, kind="regex", pattern="(")]
    assert moderation.match_rules(rules, "anything") == []


def test_pick_severity_takes_harshest():
    low = moderation.Violation("sensitive", "w", action="warn")
    high = moderation.Violation("flood", "f", action="kick")
    assert moderation.pick_severity([low, high]) is high


def test_parse_mod_command():
    assert moderation.parse_mod_command([]) == ("", [])
    assert moderation.parse_mod_command(["list"]) == ("list", [])
    assert moderation.parse_mod_command(["bogus", "x"]) == ("unknown", ["x"])


def test_parse_add_args_full():
    parsed = moderation.parse_add_args(["-n", "regex", "|", "a b", "|", "mute", "|", "300"])
    assert parsed.ok
    assert parsed.recall is False
    assert parsed.kind == "regex"
    assert parsed.pattern == "a b"
    assert parsed.action == "mute"
    assert parsed.mute_seconds == 300


def test_parse_add_args_rejects_bad_input():
    assert not moderation.parse_add_args(["keyword", "|", "x"]).ok
    assert not moderation.parse_add_args(["bogus", "|", "x", "|", "warn"]).ok
    assert not moderation.parse_add_args(["keyword", "|", "x", "|", "boom"]).ok
    assert not moderation.parse_add_args(["keyword", "|", "x", "|", "mute", "|", "abc"]).ok


def test_render_warn_substitutes_placeholders():
    text = moderation.render_warn(
        "{nickname} 注意：{reason}（{count}/{limit}）",
        nickname="小明", user_id="1", reason="刷屏", count=2, limit=3,
    )
    assert text == "小明 注意：刷屏（2/3）"


def test_decide_warn_then_escalates_to_mute():
    state = moderation.ModerationState()
    policy = _policy(warn_before_mute=2)
    first = moderation.decide(
        rules=[_rule()], text="违禁", group_id="1", user_id="9",
        state=state, now=1.0, policy=policy,
    )
    assert first.action == "warn" and first.recall and first.strike == 1
    state.mark_action("1", "9", now=1.0)
    second = moderation.decide(
        rules=[_rule()], text="违禁", group_id="1", user_id="9",
        state=state, now=2.0, policy=policy,
    )
    assert second.action == "mute" and second.strike == 2


def test_decide_respects_cooldown():
    state = moderation.ModerationState()
    policy = _policy(cooldown=30.0)
    first = moderation.decide(
        rules=[_rule()], text="违禁", group_id="1", user_id="9",
        state=state, now=1.0, policy=policy,
    )
    assert first is not None
    blocked = moderation.decide(
        rules=[_rule()], text="违禁", group_id="1", user_id="9",
        state=state, now=2.0, policy=policy,
    )
    assert blocked is None


def test_decide_flood_triggers_mute():
    state = moderation.ModerationState()
    policy = _policy(flood_window=10.0, flood_max=3)
    outcomes = [
        moderation.decide(rules=[], text="m%d" % i, group_id="1", user_id="7",
                          state=state, now=float(i), policy=policy)
        for i in range(3)
    ]
    assert outcomes[0] is None and outcomes[1] is None
    assert outcomes[2] is not None and outcomes[2].action == "mute"
    assert outcomes[2].recall is False


def test_decide_duplicate_triggers_warn():
    state = moderation.ModerationState()
    policy = _policy(duplicate_window=30.0, duplicate_max=3)
    outcomes = [
        moderation.decide(rules=[], text="复读", group_id="1", user_id="7",
                          state=state, now=float(i), policy=policy)
        for i in range(3)
    ]
    assert outcomes[2] is not None and outcomes[2].kind == "duplicate"


def test_decide_mention_all():
    state = moderation.ModerationState()
    outcome = moderation.decide(
        rules=[], text="", at_all=True, group_id="1", user_id="7",
        state=state, now=1.0, policy=_policy(),
    )
    assert outcome is not None and outcome.kind == "mention_all"


def test_decide_dict_hits():
    state = moderation.ModerationState()
    outcome = moderation.decide(
        rules=[], text="诚招刷单", dict_hits=["刷单"], group_id="1", user_id="7",
        state=state, now=1.0, policy=_policy(sensitive_action="recall_only"),
    )
    assert outcome is not None and outcome.kind == "dict"
    assert outcome.action == "recall_only" and outcome.recall


def test_decide_pinyin_and_pattern_hits():
    state = moderation.ModerationState()
    policy = _policy()
    pinyin = moderation.decide(
        rules=[], text="shuadan", pinyin_hits=["shuadan"], group_id="1", user_id="9",
        state=state, now=1.0, policy=policy,
    )
    assert pinyin is not None and pinyin.kind == "pinyin"
    state2 = moderation.ModerationState()
    pattern = moderation.decide(
        rules=[], text="http://x.com", pattern_hits=[("url", "http://x.com")],
        group_id="1", user_id="9", state=state2, now=1.0, policy=policy,
    )
    assert pattern is not None and pattern.kind == "pattern" and "网址" in pattern.reason


def test_policy_from_settings(tmp_path):
    settings = config.load_settings(
        env={}, toml_path=tmp_path / "missing.toml", load_dotenv_first=False
    )
    policy = moderation.policy_from_settings(settings)
    assert policy.flood_max == settings.moderation_flood_max_messages
    assert policy.warn_before_mute == settings.moderation_warn_before_mute


# ---------- 配置校验 ----------


def test_moderation_config_defaults(tmp_path):
    settings = config.load_settings(
        env={}, toml_path=tmp_path / "missing.toml", load_dotenv_first=False
    )
    assert settings.moderation_flood_action == "mute"
    assert settings.moderation_duplicate_action == "warn"
    assert settings.moderation_exempt_group_admins is True
    assert settings.moderation_dry_run is False
    assert "{nickname}" in settings.moderation_warn_text
    assert settings.moderation_sensitive_dict is True
    assert settings.moderation_sensitive_action == "warn"
    assert settings.moderation_sensitive_min_length == 2
    assert settings.moderation_sensitive_traditional is True
    assert settings.moderation_sensitive_pinyin is False
    assert settings.moderation_sensitive_patterns is True


def test_moderation_config_rejects_bad_action(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text('[moderation]\nflood_action = "boom"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


def test_moderation_config_rejects_bad_number(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text("[moderation]\nflood_max_messages = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


def test_moderation_config_rejects_bad_sensitive(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text('[moderation]\nsensitive_skip = "yes"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    toml.write_text('[moderation]\nsensitive_action = "boom"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    toml.write_text("[moderation]\nsensitive_min_length = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


# ---------- DB 存取 ----------


async def test_rule_crud(fresh_db):
    rule_id = await moderation.add_rule(
        "keyword", "广告", "mute", group_id="100", mute_seconds=120, note="广告"
    )
    assert rule_id > 0
    rules = await moderation.load_rules("100")
    assert any(rule.id == rule_id and rule.action == "mute" for rule in rules)
    # 全局规则也对本群可见
    global_id = await moderation.add_rule("regex", "a+", "warn")
    assert any(rule.id == global_id for rule in await moderation.load_rules("100"))
    # 别的群看不到本群规则
    other = await moderation.load_rules("200")
    assert all(rule.id != rule_id for rule in other)
    assert await moderation.delete_rule(rule_id, group_id="100") is True
    assert await moderation.delete_rule(global_id, group_id="100") is True
    assert await moderation.delete_rule(global_id) is False


async def test_list_rules_group_first(fresh_db):
    await moderation.add_rule("keyword", "全局词", "warn")
    local_id = await moderation.add_rule("keyword", "本群词", "warn", group_id="100")
    rules = await moderation.list_rules("100")
    assert rules[0].id == local_id
