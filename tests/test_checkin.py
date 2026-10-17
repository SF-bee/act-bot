"""签到测试：重复签到幂等、连续天数、累计、今日名次、榜单范围与昵称回退、渲染。"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from src.core import checkin, config, stats
from src.models.tables import Checkin

GID = "10001"


def test_parse_scope():
    assert checkin.parse_scope("") == checkin.SCOPE_MONTH
    assert checkin.parse_scope("本月") == checkin.SCOPE_MONTH
    assert checkin.parse_scope("month") == checkin.SCOPE_MONTH
    assert checkin.parse_scope("累计") == checkin.SCOPE_ALL
    assert checkin.parse_scope("全部") == checkin.SCOPE_ALL
    with pytest.raises(ValueError):
        checkin.parse_scope("上周")


async def _count_rows(db) -> int:
    async with db.get_session() as session:
        rows = (await session.execute(select(Checkin))).scalars().all()
    return len(rows)


async def test_invalid_ids_are_rejected(fresh_db):
    """非法 QQ/群号在入口就被拒绝，不会写进数据库（历史 bug：str() 绕过校验）。"""
    with pytest.raises(ValueError):
        await checkin.check_in("g1", "100001", date="2026-10-01")
    with pytest.raises(ValueError):
        await checkin.check_in(GID, "u1", date="2026-10-01")
    with pytest.raises(ValueError):
        await checkin.leaderboard("not-a-group")
    assert await _count_rows(fresh_db) == 0


async def test_first_checkin(fresh_db):
    result = await checkin.check_in(GID, "100001", display_name="小尤", date="2026-10-01")
    assert result.status == checkin.STATUS_OK
    assert (result.streak, result.total, result.rank_today, result.milestone) == (1, 1, 1, 0)
    assert result.repeated is False


async def test_repeat_same_day_keeps_one_row(fresh_db):
    await checkin.check_in(GID, "100001", date="2026-10-01")
    again = await checkin.check_in(GID, "100001", date="2026-10-01")
    assert again.status == checkin.STATUS_REPEAT and again.repeated is True
    assert again.total == 1 and again.streak == 1
    assert await _count_rows(fresh_db) == 1


async def test_streak_counts_consecutive_days(fresh_db):
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        result = await checkin.check_in(GID, "100001", date=day)
    assert result.streak == 3 and result.total == 3


async def test_streak_resets_after_gap(fresh_db):
    for day in ("2026-10-01", "2026-10-02", "2026-10-04"):
        result = await checkin.check_in(GID, "100001", date=day)
    assert result.streak == 1 and result.total == 3


async def test_streak_is_per_group(fresh_db):
    await checkin.check_in("900001", "100001", date="2026-10-01")
    await checkin.check_in("900001", "100001", date="2026-10-02")
    other = await checkin.check_in("900002", "100001", date="2026-10-03")
    assert other.streak == 1 and other.total == 1


async def test_rank_today_increments(fresh_db):
    first = await checkin.check_in(GID, "100001", date="2026-10-01")
    second = await checkin.check_in(GID, "100002", date="2026-10-01")
    assert (first.rank_today, second.rank_today) == (1, 2)


async def test_milestone_at_seven_days(fresh_db):
    days = stats.recent_dates(7, tz_name="Asia/Shanghai", anchor="2026-10-07")
    for day in sorted(days):
        result = await checkin.check_in(GID, "100001", date=day)
    assert result.total == 7 and result.streak == 7 and result.milestone == 7


async def test_leaderboard_month_vs_all(fresh_db):
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        await checkin.check_in(GID, "100001", display_name="小尤", date=day)
    await checkin.check_in(GID, "100002", display_name="阿二", date="2026-09-30")
    await checkin.check_in(GID, "100002", display_name="阿二", date="2026-10-05")

    month = await checkin.leaderboard(GID, scope=checkin.SCOPE_MONTH, date="2026-10-05")
    assert [(row.name, row.count) for row in month] == [("小尤", 3), ("阿二", 1)]

    total = await checkin.leaderboard(GID, scope=checkin.SCOPE_ALL, date="2026-10-05")
    assert [(row.name, row.count) for row in total] == [("小尤", 3), ("阿二", 2)]
    assert total[0].last_date == "2026-10-03"


async def test_leaderboard_respects_limit_and_other_groups(fresh_db):
    await checkin.check_in(GID, "100001", date="2026-10-01")
    await checkin.check_in(GID, "100002", date="2026-10-01")
    await checkin.check_in("99999", "100003", date="2026-10-01")
    rows = await checkin.leaderboard(GID, scope=checkin.SCOPE_ALL, limit=1, date="2026-10-01")
    assert len(rows) == 1
    assert all(row.user_id in {"100001", "100002"} for row in rows)


async def test_leaderboard_uses_latest_name_snapshot(fresh_db):
    await checkin.check_in(GID, "100001", display_name="旧名字", date="2026-10-01")
    await checkin.check_in(GID, "100001", display_name="新名字", date="2026-10-02")
    rows = await checkin.leaderboard(GID, scope=checkin.SCOPE_ALL)
    assert rows[0].name == "新名字"


async def test_leaderboard_falls_back_to_masked_qq(fresh_db):
    await checkin.check_in(GID, "123456789", display_name="", date="2026-10-01")
    rows = await checkin.leaderboard(GID, scope=checkin.SCOPE_ALL)
    assert rows[0].name == stats.mask_qq("123456789")


async def test_leaderboard_empty(fresh_db):
    assert await checkin.leaderboard(GID, scope=checkin.SCOPE_MONTH) == []


def _settings(tmp_path, body: str = ""):
    toml = tmp_path / "config.toml"
    toml.write_text(body, encoding="utf-8")
    return config.load_settings(env={}, toml_path=toml, load_dotenv_first=False)


def test_render_checkin_templates(tmp_path):
    settings = _settings(tmp_path)
    daily = checkin.CheckinResult(
        status=checkin.STATUS_OK, date="2026-10-01", streak=3, total=5, rank_today=2
    )
    text = checkin.render_checkin(
        daily, nickname="小尤", group_name="ACT", bot_name="Yulia", bot_title="助理", settings=settings
    )
    assert "小尤" in text and "连续 3 天" in text and "今天第 2 个到" in text

    repeat = checkin.CheckinResult(
        status=checkin.STATUS_REPEAT, date="2026-10-01", streak=3, total=5, rank_today=2
    )
    assert "已经签过" in checkin.render_checkin(repeat, nickname="小尤", settings=settings)

    milestone = checkin.CheckinResult(
        status=checkin.STATUS_OK, date="2026-10-07", streak=7, total=7, rank_today=1, milestone=7
    )
    assert "7 天" in checkin.render_checkin(milestone, nickname="小尤", settings=settings)


def test_render_keeps_unknown_placeholder(tmp_path):
    settings = _settings(tmp_path, '[checkin]\ndaily_text = "{nickname} {未知}"\n')
    result = checkin.CheckinResult(
        status=checkin.STATUS_OK, date="2026-10-01", streak=1, total=1, rank_today=1
    )
    assert checkin.render_checkin(result, nickname="小尤", settings=settings) == "小尤 {未知}"


def test_render_leaderboard():
    rows = [
        checkin.LeaderRow(user_id="100001", name="小尤", count=3, last_date="2026-10-03"),
        checkin.LeaderRow(user_id="100002", name="123****89", count=1, last_date="2026-10-05"),
    ]
    text = checkin.render_leaderboard(
        rows, scope=checkin.SCOPE_MONTH, group_name="ACT", bot_name="Yulia", bot_title="助理"
    )
    assert "签到榜（本月）" in text and "「ACT」" in text
    assert "1. 小尤 · 3 次" in text and "2. 123****89 · 1 次" in text
    assert "共 2 人上榜" in text
