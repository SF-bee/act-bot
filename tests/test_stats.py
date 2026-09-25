"""统计测试：计数口径、命令识别、快照/累加落库、渲染、隐私打码。"""
from __future__ import annotations

import pytest

from src.core import config, stats
from src.core.config import ConfigError


@pytest.fixture(autouse=True)
def _clean_state():
    stats.reset_state()
    yield
    stats.reset_state()


def test_command_name():
    assert stats.command_name("/ping") == "ping"
    assert stats.command_name("  /stats  ") == "stats"
    assert stats.command_name("/config welcome on") == "config"
    assert stats.command_name("你好") is None
    assert stats.command_name("/") == ""


def test_mask_qq():
    # 保留前 3 后 2：9 位号中间遮 4 位（长度不变）
    assert stats.mask_qq("123456789") == "123****89"
    assert stats.mask_qq("12345") == "***"


def test_format_duration():
    assert stats.format_duration(45) == "45 秒"
    assert stats.format_duration(125) == "2 分 5 秒"
    assert stats.format_duration(3600 + 12 * 60) == "1 小时 12 分"


def test_recent_dates_are_unique_and_ordered():
    dates = stats.recent_dates(3, tz_name="Asia/Shanghai")
    assert len(dates) == 3 and len(set(dates)) == 3
    assert dates == sorted(dates, reverse=True)


def test_records_accumulate_in_memory(temp_data_dir):
    tz = "Asia/Shanghai"
    stats.record_message("100", "1", "你好", tz_name=tz)
    stats.record_message("100", "1", "/stats", tz_name=tz)
    stats.record_message("100", "2", "在", tz_name=tz)
    stats.record_join("100", tz_name=tz)
    stats.record_leave("100", tz_name=tz)
    stats.record_auto_reply("100", tz_name=tz)
    data = stats.summary("100", tz_name=tz)
    assert data[stats.METRIC_MESSAGES] == 3
    assert data[stats.METRIC_COMMANDS] == 1
    assert data[stats.METRIC_ACTIVE_USERS] == 2
    assert data[stats.METRIC_JOINS] == 1 and data[stats.METRIC_LEAVES] == 1
    assert data[stats.METRIC_AUTO_REPLIES] == 1
    assert [qq for qq, _ in stats.top_users("100", limit=2, tz_name=tz)] == ["1", "2"]


def test_records_respect_feature_switch(temp_data_dir, monkeypatch):
    monkeypatch.setattr(stats, "_enabled", lambda: False)
    stats.record_message("100", "1", "你好")
    stats.record_join("100")
    stats.record_error()
    assert stats.summary("100") == {}
    assert stats.pending_errors() == 0


def test_format_stats_member_vs_admin():
    data = {
        stats.METRIC_MESSAGES: 10,
        stats.METRIC_ACTIVE_USERS: 3,
        stats.METRIC_JOINS: 1,
        stats.METRIC_LEAVES: 0,
    }
    member = stats.format_stats(
        data, bot_name="Yulia", bot_title="ACT 动漫社助理", uptime_text="2 分 5 秒"
    )
    assert "消息 10 条" in member and "活跃 3 人" in member
    assert "命令" not in member and "Top" not in member, "成员视角不该看到管理数据"

    admin = stats.format_stats(
        dict(
            data,
            **{
                stats.METRIC_COMMANDS: 4,
                stats.METRIC_AUTO_REPLIES: 2,
                stats.METRIC_ERRORS: 0,
            },
        ),
        bot_name="Yulia",
        bot_title="ACT 动漫社助理",
        uptime_text="2 分 5 秒",
        is_admin=True,
        top=[("123456789", 7)],
        history={stats.METRIC_MESSAGES: 99, stats.METRIC_JOINS: 1, stats.METRIC_LEAVES: 2},
        history_days=7,
    )
    assert "命令 4 次" in admin and "自动回复 2 条" in admin
    assert "123****89(7)" in admin, "活跃榜里的 QQ 号必须打码"
    assert "近 7 天：消息 99" in admin


def test_stats_config_defaults_and_validation(tmp_path):
    settings = config.load_settings(
        env={}, toml_path=tmp_path / "missing.toml", load_dotenv_first=False
    )
    assert settings.stats_flush_seconds == 60.0
    assert settings.stats_top_users == 5
    assert settings.stats_history_days == 7

    toml = tmp_path / "config.toml"
    toml.write_text("[stats]\nflush_seconds = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    toml.write_text("[stats]\ntop_users = -1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


async def test_flush_persists_and_accumulates(fresh_db):
    tz = "Asia/Shanghai"
    stats.record_message("100", "1", "hi", tz_name=tz)
    stats.record_message("100", "1", "again", tz_name=tz)
    assert await stats.flush(tz_name=tz) >= 1
    assert await stats.metric_today(stats.METRIC_MESSAGES, "100", tz_name=tz) == 2

    stats.record_message("100", "1", "third", tz_name=tz)
    await stats.flush(tz_name=tz)
    assert await stats.metric_today(stats.METRIC_MESSAGES, "100", tz_name=tz) == 3


async def test_active_users_is_snapshot_not_sum(fresh_db):
    tz = "Asia/Shanghai"
    stats.record_message("100", "1", "hi", tz_name=tz)
    await stats.flush(tz_name=tz)
    stats.record_message("100", "1", "hi again", tz_name=tz)  # 同一个人
    await stats.flush(tz_name=tz)
    assert await stats.metric_today(stats.METRIC_ACTIVE_USERS, "100", tz_name=tz) == 1
    assert await stats.metric_today(stats.METRIC_MESSAGES, "100", tz_name=tz) == 2


async def test_errors_are_global_and_reset_on_flush(fresh_db):
    tz = "Asia/Shanghai"
    stats.record_error()
    stats.record_error()
    assert stats.pending_errors() == 2
    await stats.flush(tz_name=tz)
    assert stats.pending_errors() == 0
    assert await stats.metric_today(stats.METRIC_ERRORS, tz_name=tz) == 2


async def test_history_excludes_today(fresh_db):
    tz = "Asia/Shanghai"
    stats.record_message("100", "1", "hi", tz_name=tz)
    await stats.flush(tz_name=tz)
    totals = await stats.history_totals("100", days=7, tz_name=tz)
    assert totals[stats.METRIC_MESSAGES] == 0, "今天的量不算进历史"

