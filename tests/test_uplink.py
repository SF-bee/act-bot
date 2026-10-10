"""协议端上下线记录测试：在线时长、离线时长、只提醒一次、渲染。"""
from __future__ import annotations

from src.core import uplink

TZ = "Asia/Shanghai"


def setup_function() -> None:
    uplink.reset()


def test_first_connect_is_not_a_recovery():
    assert uplink.mark_online("10001", now=0.0) is None
    assert uplink.pending("10001") is None


def test_offline_after_connect_reports_online_seconds():
    uplink.mark_online("10001", now=1000.0)
    outage = uplink.mark_offline("10001", detail="你的账号当前登录已失效", now=5000.0)
    assert outage.online_seconds == 4000.0
    assert outage.detail == "你的账号当前登录已失效"
    assert uplink.pending("10001") == outage


def test_offline_without_connect_has_unknown_online_seconds():
    outage = uplink.mark_offline("10001", now=1000.0)
    assert outage.online_seconds is None


def test_recovery_reports_offline_seconds_only_once():
    uplink.mark_online("10001", now=0.0)
    uplink.mark_offline("10001", now=60.0)
    recovery = uplink.mark_online("10001", now=960.0)
    assert recovery is not None
    assert recovery.offline_seconds == 900.0
    assert recovery.outage.online_seconds == 60.0
    # 掉线记录被消费掉：再次连接不再提醒（协议端自身重启也不该刷屏）
    assert uplink.mark_online("10001", now=1000.0) is None


def test_accounts_are_tracked_separately():
    uplink.mark_online("1", now=0.0)
    uplink.mark_offline("2", now=10.0)
    assert uplink.pending("1") is None
    assert uplink.pending("2") is not None


def test_render_offline_line():
    uplink.mark_online("10001", now=0.0)
    outage = uplink.mark_offline("10001", detail="账号已失效", now=3600.0)
    text = uplink.render_offline(outage, tz_name=TZ)
    assert "01-01 09:00" in text
    assert "本次在线 1 小时 0 分" in text
    assert "账号已失效" in text


def test_render_recovery_lines():
    uplink.mark_online("10001", now=0.0)
    uplink.mark_offline("10001", detail="你的账号当前登录已失效", now=3600.0)
    recovery = uplink.mark_online("10001", now=3600.0 + 7200.0)
    assert recovery is not None
    text = uplink.render_recovery(
        recovery, bot_name="Yulia", bot_title="ACT 动漫社助理", tz_name=TZ
    )
    assert text.startswith("Yulia（ACT 动漫社助理）· 协议端掉线提醒")
    assert "· 掉线 01-01 09:00（掉线前已在线 1 小时 0 分）" in text
    assert "· 离线 2 小时 0 分，01-01 11:00 已重新上线" in text
    assert "· 协议端说明：你的账号当前登录已失效" in text


def test_render_recovery_without_online_seconds():
    outage = uplink.mark_offline("10001", now=0.0)
    recovery = uplink.Recovery(outage=outage, at=600.0, offline_seconds=600.0)
    text = uplink.render_recovery(recovery, tz_name=TZ)
    assert text.splitlines()[1] == "· 掉线 01-01 08:00"
