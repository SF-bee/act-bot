"""群互动 · 骰子 / 运势 / 选一个：纯逻辑与配置测试。"""
from __future__ import annotations

import random

import pytest

from src.core import config, fun
from src.core.config import ConfigError

TEXTS = ("大吉|今天很棒", "小吉|还不错", "凶|早点睡")


def _load(tmp_path, body: str):
    toml = tmp_path / "config.toml"
    toml.write_text(body, encoding="utf-8")
    return config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


# ---------- 骰子 ----------

def test_parse_dice_forms():
    assert fun.parse_dice("2d6") == (2, 6)
    assert fun.parse_dice("d20") == (1, 20)
    assert fun.parse_dice("6") == (1, 6)
    assert fun.parse_dice("1D10") == (1, 10)


@pytest.mark.parametrize(
    "spec",
    ["", "0d6", "21d6", "2d1", "2d1001", "abc", "2d6x", "-1d6"],
)
def test_parse_dice_invalid(spec):
    with pytest.raises(ValueError):
        fun.parse_dice(spec)


def test_roll_dice_uses_injected_rng():
    result = fun.roll_dice("2d6", rng=random.Random(42))
    assert result.spec == "2d6"
    assert result.count == 2 and result.sides == 6
    assert len(result.rolls) == 2
    assert all(1 <= item <= 6 for item in result.rolls)
    assert result.total == sum(result.rolls)


def test_roll_dice_normalizes_bare_sides():
    result = fun.roll_dice("6", rng=random.Random(1))
    assert result.spec == "1d6"
    assert 1 <= result.rolls[0] <= 6


def test_render_dice_single_and_multi():
    one = fun.DiceResult(spec="1d6", count=1, sides=6, rolls=(4,), total=4)
    assert fun.render_dice(one) == "🎲 1d6 开摇！结果是：4～"

    two = fun.DiceResult(spec="2d6", count=2, sides=6, rolls=(3, 5), total=8)
    assert fun.render_dice(two) == "🎲 2d6 开摇！3 + 5 = 8，合计 8 点！"


# ---------- 运势 ----------

def test_fortune_is_stable_per_user_and_day():
    first = fun.fortune("10001", date="2026-10-01", texts=TEXTS)
    second = fun.fortune("10001", date="2026-10-01", texts=TEXTS)
    assert first == second


def test_fortune_changes_with_day_or_user():
    base = fun.fortune("10001", date="2026-10-01", texts=TEXTS)
    next_day = fun.fortune("10001", date="2026-10-02", texts=TEXTS)
    other_user = fun.fortune("10002", date="2026-10-01", texts=TEXTS)
    assert base != next_day
    assert base != other_user


def test_fortune_without_separator_falls_back_to_default_level():
    result = fun.fortune("10001", date="2026-10-01", texts=("只有文案",))
    assert result.level == "运势"
    assert result.text == "只有文案"
    assert 1 <= result.lucky <= 99


def test_fortune_empty_texts_is_rejected():
    with pytest.raises(ValueError):
        fun.fortune("10001", date="2026-10-01", texts=())


def test_render_fortune_keeps_unknown_placeholder():
    result = fun.Fortune(level="大吉", text="{nickname} 今天 {未知}", lucky=7)
    text = fun.render_fortune(result, nickname="小明", date="2026-10-01")
    assert "大吉" in text and "小明" in text
    assert "{未知}" in text
    assert "幸运数字：7" in text


# ---------- 选一个 ----------

def test_parse_options_supports_common_separators():
    assert fun.parse_options("火锅,烤肉、拉面；寿司") == ["火锅", "烤肉", "拉面", "寿司"]
    assert fun.parse_options("  火锅   烤肉  ") == ["火锅", "烤肉"]


def test_choose_returns_a_candidate():
    options = ["火锅", "烤肉", "拉面"]
    assert fun.choose(options, rng=random.Random(7)) in options


def test_choose_rejects_too_few_or_too_many():
    with pytest.raises(ValueError):
        fun.choose(["只有一个"])
    with pytest.raises(ValueError):
        fun.choose([f"选项{i}" for i in range(fun.MAX_OPTIONS + 1)])


# ---------- 配置 ----------

def test_default_fortune_texts_are_usable(tmp_path):
    settings = _load(tmp_path, "")
    assert len(settings.fun_fortune_texts) >= 1
    assert all("|" in item for item in settings.fun_fortune_texts)


def test_custom_fortune_texts_are_loaded(tmp_path):
    settings = _load(
        tmp_path,
        '[fun]\nfortune_texts = ["大吉|今天很棒", "没有分隔符"]\n',
    )
    assert settings.fun_fortune_texts == ("大吉|今天很棒", "没有分隔符")


@pytest.mark.parametrize(
    "body",
    [
        "[fun]\nfortune_texts = []\n",
        '[fun]\nfortune_texts = "不是数组"\n',
        "[fun]\nfortune_texts = [1]\n",
        '[fun]\nfortune_texts = [""]\n',
        '[fun]\nfortune_texts = ["' + "x" * (fun.MAX_FORTUNE_TEXT + 1) + '"]\n',
        "fun = 1\n",
    ],
)
def test_invalid_fortune_config_is_rejected(tmp_path, body):
    with pytest.raises(ConfigError):
        _load(tmp_path, body)
