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
