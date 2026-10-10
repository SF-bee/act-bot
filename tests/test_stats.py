"""统计测试：计数口径、命令识别、区间解析、落库合并、走势、日报、隐私打码。"""
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


def test_recent_dates_unique_ordered_and_anchored():
    dates = stats.recent_dates(3, tz_name="Asia/Shanghai")
    assert len(dates) == 3 and len(set(dates)) == 3
    assert dates == sorted(dates, reverse=True)
    anchored = stats.recent_dates(3, tz_name="Asia/Shanghai", anchor="2026-10-07")
    assert anchored == ["2026-10-07", "2026-10-06", "2026-10-05"]


def test_parse_range_forms():
    tz = "Asia/Shanghai"
    today = stats.today(tz)
    assert stats.parse_range("", tz_name=tz).label == "今天"
    assert stats.parse_range("今天", tz_name=tz).dates == (today,)

    yesterday = stats.recent_dates(2, tz_name=tz, anchor=today)[-1]
    assert stats.parse_range("昨天", tz_name=tz).dates == (yesterday,)

    week = stats.parse_range("本周", tz_name=tz)
    assert week.label == "本周" and week.dates[0] == today and 1 <= week.days <= 7
    assert stats.parse_range("上周", tz_name=tz).days == 7

    month = stats.parse_range("本月", tz_name=tz)
    assert month.label == "本月" and month.dates[0] == today

    assert stats.parse_range("近30天", tz_name=tz).label == "近 30 天"
    assert stats.parse_range("近30天", tz_name=tz).days == 30
    assert stats.parse_range("7天", tz_name=tz).days == 7
    assert stats.parse_range("last 7 days", tz_name=tz).days == 7
    assert stats.parse_range("1000天", tz_name=tz, max_days=30).days == 30

    assert stats.parse_range("随便", tz_name=tz) is None
    assert stats.parse_range("0", tz_name=tz) is None


def test_sparkline():
    assert stats.sparkline([]) == ""
    assert stats.sparkline([0, 0]) == "··"
    line = stats.sparkline([0, 1, 2, 4, 8])
    assert len(line) == 5
    assert line[0] == "·"
    assert line[-1] == "█"


def test_summarize_multi_day():
    days = [
        stats.DailyStat(date="2026-10-01", messages=10, active_users=3, joins=1),
        stats.DailyStat(date="2026-10-02", messages=20, active_users=5, leaves=2),
    ]
    data = stats.summarize(days)
    assert data[stats.METRIC_MESSAGES] == 30
    assert data["message_avg"] == 15
    assert data[stats.METRIC_ACTIVE_USERS] == 5, "跨天活跃人数取峰值，不能相加"
    assert data["active_avg"] == 4
    assert data["days"] == 2


async def test_records_accumulate(fresh_db):
    tz = "Asia/Shanghai"
    stats.record_message("100", "1", "你好", tz_name=tz)
    stats.record_message("100", "1", "/stats", tz_name=tz)
    stats.record_message("100", "2", "在", tz_name=tz)
    stats.record_join("100", tz_name=tz)
    stats.record_leave("100", tz_name=tz)
    stats.record_auto_reply("100", tz_name=tz)
    stat = (await stats.daily_series("100", [stats.today(tz)], tz_name=tz))[0]
    assert stat.messages == 3
    assert stat.commands == 1
    assert stat.active_users == 2
    assert stat.joins == 1 and stat.leaves == 1
    assert stat.auto_replies == 1
    assert [qq for qq, _ in stats.top_users("100", limit=2, tz_name=tz)] == ["1", "2"]


def test_records_respect_feature_switch(temp_data_dir, monkeypatch):
    monkeypatch.setattr(stats, "_enabled", lambda: False)
    stats.record_message("100", "1", "你好")
    stats.record_join("100")
    stats.record_error()
    assert stats.pending_errors() == 0
    assert stats.top_users("100") == []


async def test_today_totals_survive_flush(fresh_db):
    """回归：旧实现里 flush 会清空 pending，导致今日数字每隔一个落库周期归零。"""
    tz = "Asia/Shanghai"
    for _ in range(10):
        stats.record_message("100", "1", "hi", tz_name=tz)
    await stats.flush(tz_name=tz)
    stat = (await stats.daily_series("100", [stats.today(tz)], tz_name=tz))[0]
    assert stat.messages == 10, "落库后今日数字不能归零"

    stats.record_message("100", "1", "again", tz_name=tz)
    stat = (await stats.daily_series("100", [stats.today(tz)], tz_name=tz))[0]
    assert stat.messages == 11, "内存增量要叠加到已落库的值上"


async def test_active_users_never_shrinks(fresh_db):
    """活跃人数是当日去重人数：重启后内存清空，也不能把小值写回去。"""
    tz = "Asia/Shanghai"
    stats.record_message("100", "1", "a", tz_name=tz)
    stats.record_message("100", "2", "b", tz_name=tz)
    await stats.flush(tz_name=tz)
    assert await stats.metric_today(stats.METRIC_ACTIVE_USERS, "100", tz_name=tz) == 2

    stats.reset_state()  # 模拟重启
    stats.record_message("100", "1", "c", tz_name=tz)
    await stats.flush(tz_name=tz)
    assert await stats.metric_today(stats.METRIC_ACTIVE_USERS, "100", tz_name=tz) == 2
    assert (await stats.daily_series("100", [stats.today(tz)], tz_name=tz))[0].active_users == 2


async def test_flush_persists_and_accumulates(fresh_db):
    tz = "Asia/Shanghai"
    stats.record_message("100", "1", "hi", tz_name=tz)
    stats.record_message("100", "1", "again", tz_name=tz)
    assert await stats.flush(tz_name=tz) >= 1
    assert await stats.metric_today(stats.METRIC_MESSAGES, "100", tz_name=tz) == 2

    stats.record_message("100", "1", "third", tz_name=tz)
    await stats.flush(tz_name=tz)
    assert await stats.metric_today(stats.METRIC_MESSAGES, "100", tz_name=tz) == 3


async def test_errors_are_global_and_reset_on_flush(fresh_db):
    tz = "Asia/Shanghai"
    stats.record_error()
    stats.record_error()
    assert stats.pending_errors() == 2
    assert await stats.errors_total([stats.today(tz)], tz_name=tz) == 2
    await stats.flush(tz_name=tz)
    assert stats.pending_errors() == 0
    assert await stats.errors_total([stats.today(tz)], tz_name=tz) == 2


async def test_daily_series_reads_history(fresh_db):
    from src.core import db
    from src.models.tables import StatsDaily

    async with db.get_session() as session:
        session.add_all(
            [
                StatsDaily(group_id="100", date="2026-10-01", metric=stats.METRIC_MESSAGES, value=5),
                StatsDaily(
                    group_id="100", date="2026-10-01", metric=stats.METRIC_ACTIVE_USERS, value=2
                ),
                StatsDaily(group_id="100", date="2026-10-02", metric=stats.METRIC_MESSAGES, value=7),
            ]
        )
        await session.commit()

    series = await stats.daily_series(
        "100", ["2026-10-02", "2026-10-01"], tz_name="Asia/Shanghai"
    )
    assert [item.messages for item in series] == [7, 5]
    assert series[1].active_users == 2


async def test_daily_digest_and_render(fresh_db):
    from src.core import db, groups
    from src.models.tables import StatsDaily

    async with db.get_session() as session:
        session.add(
            StatsDaily(
                group_id="1058617245", date="2026-10-06", metric=stats.METRIC_MESSAGES, value=88
            )
        )
        await session.commit()
    await groups.set_feature("1058617245", "stats", True, group_name="测试群")

    digest = await stats.daily_digest(tz_name="Asia/Shanghai", date="2026-10-06")
    assert digest.date == "2026-10-06"
    assert len(digest.entries) == 1
    text = stats.render_digest(digest, bot_name="Yulia", bot_title="ACT 动漫社助理")
    assert "2026-10-06" in text
    assert "测试群" in text
    assert "消息 88" in text


async def test_daily_digest_empty_renders_nothing(fresh_db):
    digest = await stats.daily_digest(tz_name="Asia/Shanghai", date="2026-01-01")
    assert digest.entries == ()
    assert stats.render_digest(digest, bot_name="Y", bot_title="T") == ""


def test_format_stats_member_vs_admin():
    day = stats.DailyStat(date="2026-10-01", messages=10, active_users=3, joins=1)
    data = stats.summarize([day])
    member = stats.format_stats(
        data,
        bot_name="Yulia",
        bot_title="ACT 动漫社助理",
        uptime_text="2 分 5 秒",
        range_label="今天",
        series=[day],
    )
    assert "消息 10 条" in member and "活跃 3 人" in member
    assert "命令" not in member and "Top" not in member, "成员视角不该看到管理数据"
    assert "近 1 日" in member and "峰值 2026-10-01（10 条）" in member

    admin = stats.format_stats(
        dict(data, **{stats.METRIC_COMMANDS: 4, stats.METRIC_AUTO_REPLIES: 2}),
        bot_name="Yulia",
        bot_title="ACT 动漫社助理",
        uptime_text="2 分 5 秒",
        range_label="今天",
        series=[day],
        is_admin=True,
        top=[("123456789", 7)],
        errors=0,
    )
    assert "命令 4 次" in admin and "自动回复 2 条" in admin
    assert "123****89(7)" in admin, "活跃榜里的 QQ 号必须打码"


def test_format_stats_hides_trend_when_empty():
    days = [stats.DailyStat(date="2026-10-01"), stats.DailyStat(date="2026-10-02")]
    text = stats.format_stats(
        stats.summarize(days),
        bot_name="Y",
        bot_title="T",
        uptime_text="1 分",
        range_label="今天",
        series=days,
    )
    assert "近" not in text
    assert "峰值" not in text


def test_format_stats_multi_day_shows_averages():
    days = [
        stats.DailyStat(date="2026-10-01", messages=10, active_users=3),
        stats.DailyStat(date="2026-10-02", messages=20, active_users=5),
    ]
    text = stats.format_stats(
        stats.summarize(days),
        bot_name="Y",
        bot_title="T",
        uptime_text="1 分",
        range_label="近 2 天",
        series=days,
    )
    assert "消息 30 条｜日均 15 条" in text
    assert "活跃 5 人（日均 4 人）" in text
    assert "近 2 日" in text


def test_stats_config_defaults_and_validation(tmp_path):
    settings = config.load_settings(
        env={}, toml_path=tmp_path / "missing.toml", load_dotenv_first=False
    )
    assert settings.stats_flush_seconds == 60.0
    assert settings.stats_top_users == 5
    assert settings.stats_trend_days == 7
    assert settings.stats_range_max_days == 90
    assert settings.stats_digest_at == "09:00"

    toml = tmp_path / "config.toml"
    toml.write_text("[stats]\nflush_seconds = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    toml.write_text("[stats]\ntop_users = -1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    toml.write_text("[stats]\ntrend_days = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    toml.write_text("[stats]\nrange_max_days = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    toml.write_text("[stats]\ndigest_at = \"25:00\"\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)
    toml.write_text("[stats]\ndigest_at = \"off\"\n", encoding="utf-8")
    assert config.load_settings(
        env={}, toml_path=toml, load_dotenv_first=False
    ).stats_digest_at == ""
