"""人设测试：默认值、配置覆盖与校验、称呼判断。"""
from __future__ import annotations

import pytest

from src.core import config, persona
from src.core.config import ConfigError


def test_defaults(tmp_path):
    settings = config.load_settings(
        env={}, toml_path=tmp_path / "missing.toml", load_dotenv_first=False
    )
    assert settings.persona_name == "Yulia"
    assert settings.persona_title == "ACT 动漫社助理"
    assert "Yulia" in settings.persona_aliases


def test_config_override_and_alias_dedup(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text(
        '[persona]\nname = "小助手"\ntitle = "社团助理"\naliases = ["助手", "小助手"]\n',
        encoding="utf-8",
    )
    settings = config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    assert settings.persona_name == "小助手"
    assert settings.persona_title == "社团助理"
    assert settings.persona_aliases == ("小助手", "助手"), "名字本身算称呼且去重、排首位"


def test_config_rejects_bad_persona(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text('[persona]\nname = ""\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    toml.write_text('[persona]\naliases = "Yulia"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


def test_alias_matches_is_case_insensitive():
    assert persona.alias_matches("hello YULIA", ["Yulia"]) is True
    assert persona.alias_matches("尤莉娅在吗", ["尤莉娅"]) is True
    assert persona.alias_matches("overwatch 好玩", ["Yulia"]) is False
    assert persona.alias_matches("", ["Yulia"]) is False


def test_format_intro():
    assert persona.format_intro("Yulia", "ACT 动漫社助理") == "Yulia｜ACT 动漫社助理"
    assert persona.format_intro("Yulia", "") == "Yulia"
    assert persona.format_intro("", "社团助理") == "社团助理"


def test_settings_backed_helpers(temp_data_dir):
    assert persona.name() == "Yulia"
    assert persona.title() == "ACT 动漫社助理"
    assert persona.intro() == "Yulia｜ACT 动漫社助理"
    assert persona.is_called("Yulia 早") is True
    assert persona.is_called("尤莉在吗") is True
    assert persona.is_called("晚安") is False

