"""配置加载测试（部署层 / 业务层分离）。"""
from __future__ import annotations

import pytest

from src.core import config
from src.core.config import ConfigError


def test_defaults(tmp_path):
    settings = config.load_settings(
        env={}, toml_path=tmp_path / "missing.toml", load_dotenv_first=False
    )
    assert settings.timezone == "Asia/Shanghai"
    assert settings.backup_daily_at == "03:00"
    assert settings.feature("welcome") is True
    assert settings.feature("checkin") is False
    assert settings.feature("不存在的开关") is True  # 未定义默认开启


def test_reads_toml(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[features]
welcome = false

[broadcast]
interval_seconds = 5

[backup]
daily_at = "04:30"
keep_daily_days = 7
""",
        encoding="utf-8",
    )
    settings = config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    assert settings.feature("welcome") is False
    assert settings.broadcast_interval_seconds == 5.0
    assert config.parse_hhmm(settings.backup_daily_at) == (4, 30)
    assert settings.backup_keep_daily_days == 7


def test_alert_uplink_switch(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text("[alert]\nuplink = false\n", encoding="utf-8")
    settings = config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    assert settings.alert_uplink is False

    # 未配置时默认开启
    missing = tmp_path / "missing.toml"
    assert config.load_settings(env={}, toml_path=missing, load_dotenv_first=False).alert_uplink is True


def test_invalid_alert_uplink(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text('[alert]\nuplink = "yes"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


def test_env_overrides(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text('[backup]\ndaily_at = "01:00"\n', encoding="utf-8")
    settings = config.load_settings(
        env={"ACTBOT_TIMEZONE": "UTC", "ACTBOT_BOOTSTRAP_ADMIN_QQ": "10001"},
        toml_path=toml,
        load_dotenv_first=False,
    )
    assert settings.timezone == "UTC"
    assert settings.bootstrap_admin_qq == "10001"


@pytest.mark.parametrize("value", ["25:00", "abc", "3:5", "12:60"])
def test_invalid_time(tmp_path, value):
    toml = tmp_path / "config.toml"
    toml.write_text(f'[backup]\ndaily_at = "{value}"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


def test_feature_toggle_type_error(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text('[features]\nwelcome = "yes"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


def test_checkin_defaults(tmp_path):
    settings = config.load_settings(
        env={}, toml_path=tmp_path / "missing.toml", load_dotenv_first=False
    )
    assert settings.checkin_rank_size == 10
    assert settings.checkin_rank_scope == "month"
    assert "{streak}" in settings.checkin_daily_text
    assert settings.feature("checkin") is False  # 默认关，需显式打开


def test_checkin_reads_toml(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text(
        '[checkin]\nrank_size = 3\nrank_scope = "all"\ndaily_text = "hi {nickname}"\n',
        encoding="utf-8",
    )
    settings = config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    assert settings.checkin_rank_size == 3
    assert settings.checkin_rank_scope == "all"
    assert settings.checkin_daily_text == "hi {nickname}"


@pytest.mark.parametrize("body", ['rank_size = 0', 'rank_size = 51', 'rank_size = "10"', 'rank_scope = "week"', 'daily_text = ""'])
def test_checkin_invalid(tmp_path, body):
    toml = tmp_path / "config.toml"
    toml.write_text("[checkin]\n" + body + "\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


def test_stats_flush_timeout_default_and_override(tmp_path):
    toml = tmp_path / "config.toml"
    settings = config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    assert settings.stats_flush_timeout == 10.0

    toml.write_text("[stats]\nflush_timeout_seconds = 2.5\n", encoding="utf-8")
    settings = config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    assert settings.stats_flush_timeout == 2.5

    toml.write_text("[stats]\nflush_timeout_seconds = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="flush_timeout_seconds"):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)

def test_unknown_feature_key_is_rejected(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text("[features]\nwelcom = true\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="未知功能开关"):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


def test_all_registered_feature_keys_are_accepted(tmp_path):
    from src.core import features as features_mod

    toml = tmp_path / "config.toml"
    body = "[features]\n" + "\n".join(f"{name} = false" for name in features_mod.names())
    toml.write_text(body + "\n", encoding="utf-8")
    settings = config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    assert all(settings.feature(name) is False for name in features_mod.names())