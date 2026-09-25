"""入群欢迎测试：消息渲染（纯函数）+ 群级开关（数据库）+ 配置解析。"""
from __future__ import annotations

import json

import pytest

from src.core import config, groups
from src.core.config import ConfigError


def test_render_welcome_mentions_newcomer():
    from src.core.welcome import render_welcome

    message = render_welcome(
        "欢迎 {nickname} 加入 {group_name}！",
        nickname="小尤",
        group_name="ACT 动漫社",
        user_id="123456",
    )
    raw = str(message)
    assert "[CQ:at,qq=123456]" in raw
    assert "欢迎 小尤 加入 ACT 动漫社！" in message.extract_plain_text()


def test_render_welcome_without_mention():
    from src.core.welcome import render_welcome

    message = render_welcome(
        "hello {nickname}", nickname="X", group_name="G", user_id="1", at_newcomer=False
    )
    assert "[CQ:at" not in str(message)
    assert message.extract_plain_text() == "hello X"


def test_render_welcome_keeps_unknown_placeholder():
    from src.core.welcome import render_welcome

    message = render_welcome(
        "{unknown} 你好", nickname="n", group_name="g", user_id="1", at_newcomer=False
    )
    assert "{unknown}" in message.extract_plain_text()


def test_render_welcome_substitutes_bot_identity():
    from src.core.welcome import render_welcome

    message = render_welcome(
        "我是 {bot_title} {bot_name}",
        nickname="n", group_name="g", user_id="1", at_newcomer=False,
        bot_name="Yulia", bot_title="ACT 动漫社助理",
    )
    assert message.extract_plain_text() == "我是 ACT 动漫社助理 Yulia"


def test_default_welcome_text_uses_persona_placeholder(tmp_path):
    settings = config.load_settings(
        env={}, toml_path=tmp_path / "missing.toml", load_dotenv_first=False
    )
    assert "{nickname}" in settings.welcome_text
    assert "{bot_name}" in settings.welcome_text


def test_parse_action():
    from src.core.welcome import parse_action

    assert parse_action("/welcome") == ""
    assert parse_action("/welcome on") == "on"
    assert parse_action("/welcome OFF") == "off"
    assert parse_action("/welcome  on  ") == "on"
    # 中文参数不再识别（命令与参数统一英文）
    assert parse_action("/welcome 开") == "unknown"
    assert parse_action("/welcome whatever") == "unknown"


async def test_group_welcome_default_enabled(fresh_db):
    assert await groups.welcome_enabled("123456789") is True


async def test_group_welcome_toggle(fresh_db):
    await groups.set_feature("123456789", groups.FEATURE_WELCOME, False, group_name="测试群")
    assert await groups.welcome_enabled("123456789") is False
    row = await groups.get_group("123456789")
    assert row is not None and row.name == "测试群"
    assert json.loads(row.features)[groups.FEATURE_WELCOME] is False
    await groups.set_feature("123456789", groups.FEATURE_WELCOME, True)
    assert await groups.welcome_enabled("123456789") is True
    row = await groups.get_group("123456789")
    assert row is not None and row.name == "测试群"
    assert json.loads(row.features)[groups.FEATURE_WELCOME] is True


def test_welcome_config_defaults(tmp_path):
    settings = config.load_settings(
        env={}, toml_path=tmp_path / "missing.toml", load_dotenv_first=False
    )
    assert "{nickname}" in settings.welcome_text
    assert settings.welcome_at_newcomer is True


def test_welcome_config_reads_toml(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text(
        '[welcome]\ntext = "hi {nickname}"\nat_newcomer = false\n', encoding="utf-8"
    )
    settings = config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    assert settings.welcome_text == "hi {nickname}"
    assert settings.welcome_at_newcomer is False


def test_welcome_config_rejects_bad_values(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text('[welcome]\ntext = ""\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    toml.write_text('[welcome]\nat_newcomer = "yes"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)

