"""聊天引擎测试：命令解析、匹配、加权随机、状态机、冷却、规则存取。"""
from __future__ import annotations

import random

import pytest

from src.core import chat, config
from src.core.chat import ChatState, Rule
from src.core.config import ConfigError


def _rule(
    kind: str,
    reply: str,
    *,
    pattern: str = "",
    weight: int = 1,
    group_id: str = "",
    rid: int = 0,
    enabled: bool = True,
) -> Rule:
    return Rule(
        id=rid, group_id=group_id, kind=kind, pattern=pattern,
        reply=reply, weight=weight, enabled=enabled,
    )


# ---------- 命令解析 ----------


def test_parse_chat_command():
    assert chat.parse_chat_command("/chat") == ("", [])
    assert chat.parse_chat_command("/chat list") == ("list", [])
    assert chat.parse_chat_command("/chat list keyword") == ("list", ["keyword"])
    assert chat.parse_chat_command("/chat add keyword 早 早上好呀") == (
        "add", ["keyword", "早", "早上好呀"]
    )
    assert chat.parse_chat_command("/chat nope") == ("unknown", [])


def test_parse_add_args_keyword_needs_pattern():
    assert chat.parse_add_args(["keyword", "早上好", "早上好", "呀"]) == (
        "group", "keyword", "早上好", "早上好 呀",
    )
    assert chat.parse_add_args(["-g", "regex", "^早", "早上好"]) == (
        "global", "regex", "^早", "早上好",
    )


def test_parse_add_args_mention_has_no_pattern():
    assert chat.parse_add_args(["mention", "在的喵", "～"]) == ("group", "mention", "", "在的喵 ～")
    assert chat.parse_add_args(["-g", "mention_tired", "别叫了"]) == (
        "global", "mention_tired", "", "别叫了",
    )


def test_parse_add_args_rejects_invalid():
    assert chat.parse_add_args(["nope", "x", "y"])[1] == ""
    assert chat.parse_add_args(["keyword", "早"])[1] == ""  # 缺回复
    assert chat.parse_add_args([])[1] == ""


# ---------- 候选池与匹配 ----------


def test_pool_for_group_overrides_global():
    rules = [
        _rule("mention", "全局回复", group_id="", rid=1),
        _rule("mention", "本群回复", group_id="100", rid=2),
    ]
    assert [r.reply for r in chat.pool_for(rules, "100", "mention")] == ["本群回复"]
    assert [r.reply for r in chat.pool_for(rules, "999", "mention")] == ["全局回复"]


def test_match_rules_keyword_and_regex():
    rules = [
        _rule("keyword", "a", pattern="早上好", rid=1),
        _rule("regex", "b", pattern=r"^晚安", rid=2),
        _rule("keyword", "c", pattern="不存在", rid=3),
        _rule("regex", "d", pattern="([", rid=4),  # 非法正则：跳过而不炸
    ]
    assert sorted(r.id for r in chat.match_rules(rules, "早上好，晚安啦")) == [1]
    assert sorted(r.id for r in chat.match_rules(rules, "晚安啦")) == [2]


def test_match_rules_keyword_is_case_insensitive():
    rules = [_rule("keyword", "a", pattern="Yulia", rid=1)]
    assert [r.id for r in chat.match_rules(rules, "yulia 在吗")] == [1]


def test_disabled_rules_are_ignored():
    rules = [
        _rule("keyword", "a", pattern="早", rid=1, enabled=False),
        _rule("mention", "b", rid=2, enabled=False),
    ]
    assert chat.match_rules(rules, "早上好") == []
    assert chat.pool_for(rules, "1", "mention") == []


# ---------- 加权随机 ----------


def test_pick_weighted_ignores_zero_weight():
    rules = [_rule("mention", "零权重", weight=0, rid=1), _rule("mention", "有权重", weight=5, rid=2)]
    for seed in range(5):
        picked = chat.pick_weighted(rules, random.Random(seed))
        assert picked is not None and picked.id == 2


def test_pick_weighted_handles_all_zero_and_empty():
    rules = [_rule("mention", "a", weight=0, rid=1), _rule("mention", "b", weight=0, rid=2)]
    assert chat.pick_weighted(rules, random.Random(0)).id in (1, 2)
    assert chat.pick_weighted([], random.Random(0)) is None


# ---------- 档位 ----------


def test_mention_level_and_ladder():
    assert (chat.mention_level(1), chat.mention_level(2), chat.mention_level(3), chat.mention_level(9)) == (1, 2, 3, 3)
    assert chat.ladder_kinds(1) == ("mention",)
    assert chat.ladder_kinds(2) == ("mention_more", "mention")
    assert chat.ladder_kinds(3) == ("mention_tired", "mention_more", "mention")


# ---------- 决策 ----------


def test_decide_mention_escalates():
    rules = [
        _rule("mention", "常规", rid=1),
        _rule("mention_more", "又叫我", rid=2),
        _rule("mention_tired", "别叫了", rid=3),
    ]
    state = ChatState()
    reasons = [
        chat.decide(
            rules, text="Yulia", at_self=True, group_id="100", user_id="9",
            state=state, now=1000.0 + step, cooldown=0.0,
            escalate_window=120.0, rng=random.Random(step),
        ).reason
        for step in range(4)
    ]
    assert reasons == ["mention", "mention_more", "mention_tired", "mention_tired"]


def test_decide_mention_falls_back_when_high_level_missing():
    rules = [_rule("mention", "只有常规", rid=1)]
    state = ChatState()
    decision = None
    for step in range(3):
        decision = chat.decide(
            rules, text="Yulia", at_self=True, group_id="100", user_id="9",
            state=state, now=1000.0 + step, cooldown=0.0, rng=random.Random(0),
        )
    assert decision is not None and decision.reason == "mention"
    assert decision.reply == "只有常规"


def test_decide_cooldown_only_after_real_reply():
    rules = [_rule("mention", "在的", rid=1)]
    state = ChatState()
    kwargs = dict(text="Yulia", at_self=True, group_id="100", user_id="9", cooldown=20.0)
    first = chat.decide(rules, state=state, now=100.0, rng=random.Random(0), **kwargs)
    blocked = chat.decide(rules, state=state, now=110.0, rng=random.Random(0), **kwargs)
    again = chat.decide(rules, state=state, now=121.0, rng=random.Random(0), **kwargs)
    assert (first.reason, blocked.reason, again.reason) == ("mention", "cooled", "mention")


def test_decide_keyword_probability():
    rules = [_rule("keyword", "早上好呀", pattern="早上好", rid=1)]
    common = dict(text="早上好", at_self=False, group_id="100", user_id="9", cooldown=0.0)
    missed = chat.decide(rules, state=ChatState(), now=1.0, probability=0.0, rng=random.Random(0), **common)
    hit = chat.decide(rules, state=ChatState(), now=1.0, probability=1.0, rng=random.Random(0), **common)
    assert missed.reason == "missed" and missed.reply is None
    assert hit.reason == "keyword" and hit.reply == "早上好呀"


def test_decide_returns_no_match_for_unrelated_text():
    rules = [_rule("keyword", "x", pattern="不相关", rid=1)]
    decision = chat.decide(
        rules, text="随便说说", at_self=False, group_id="100", user_id="9",
        state=ChatState(), now=1.0, cooldown=0.0, rng=random.Random(0),
    )
    assert decision.reason == "no_match" and decision.reply is None


def test_render_reply_uses_persona(temp_data_dir):
    text = chat.render_reply("我是 {bot_name}（{bot_title}），{nickname} 你好", user_id="123", nickname="小明")
    assert text == "我是 Yulia（ACT 动漫社助理），小明 你好"
    assert chat.render_reply("{unknown}", user_id="123") == "{unknown}"


# ---------- 配置 ----------


def test_chat_config_defaults_and_validation(tmp_path):
    settings = config.load_settings(
        env={}, toml_path=tmp_path / "missing.toml", load_dotenv_first=False
    )
    assert settings.chat_reply_probability == 0.6
    assert settings.chat_cooldown_seconds == 20.0
    assert settings.chat_escalate_after == 3

    toml = tmp_path / "config.toml"
    toml.write_text("[chat]\nreply_probability = 1.5\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    toml.write_text("[chat]\nescalate_after = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


# ---------- 规则存取（数据库） ----------


async def test_migration_seeds_global_rules(fresh_db):
    rules = await chat.load_rules("999")
    assert rules, "迁移 003 应预置全局默认规则"
    assert all(rule.group_id == "" for rule in rules)
    kinds = {rule.kind for rule in rules}
    assert {chat.KIND_MENTION, chat.KIND_MENTION_MORE, chat.KIND_MENTION_TIRED} <= kinds


async def test_add_list_delete_rule(fresh_db):
    rule_id = await chat.add_rule(chat.KIND_KEYWORD, "晚安", "晚安好梦", group_id="100")
    listed = await chat.list_rules("100")
    assert any(rule.id == rule_id and rule.reply == "晚安好梦" for rule in listed)
    assert listed[0].id == rule_id, "本群规则应排在全局规则之前"
    assert await chat.delete_rule(rule_id, group_id="200") is False, "别的群不能删"
    assert await chat.delete_rule(rule_id, group_id="100") is True
    assert await chat.delete_rule(rule_id, group_id="100") is False


async def test_add_rule_rejects_unknown_kind(fresh_db):
    with pytest.raises(ValueError):
        await chat.add_rule("nope", "x", "y", group_id="100")

