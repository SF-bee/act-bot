"""退出流程：统计落库超时 / 失败只记日志，不阻塞退出。"""
from __future__ import annotations

import asyncio
import logging


def test_shutdown_flush_timeout_logs_pending(temp_data_dir, monkeypatch, caplog):
    from src.core import stats
    from src.bot import flush_stats_on_shutdown

    async def slow_flush(*, tz_name=None):
        await asyncio.sleep(5)
        return 0

    monkeypatch.setattr(stats, "flush", slow_flush)
    monkeypatch.setattr(
        stats, "pending_counts", lambda: {"pending": 3, "errors": 1, "groups": 2}
    )
    with caplog.at_level(logging.WARNING, logger="actbot.bot"):
        asyncio.run(asyncio.wait_for(flush_stats_on_shutdown(timeout=0.05), timeout=2))

    assert "退出时统计落库超时" in caplog.text
    assert "pending=3 errors=1 groups=2" in caplog.text


def test_shutdown_flush_failure_logs_pending(temp_data_dir, monkeypatch, caplog):
    from src.core import stats
    from src.bot import flush_stats_on_shutdown

    async def boom_flush(*, tz_name=None):
        raise RuntimeError("disk full")

    monkeypatch.setattr(stats, "flush", boom_flush)
    monkeypatch.setattr(
        stats, "pending_counts", lambda: {"pending": 5, "errors": 0, "groups": 1}
    )
    with caplog.at_level(logging.ERROR, logger="actbot.bot"):
        asyncio.run(flush_stats_on_shutdown(timeout=1))

    assert "退出时统计落库失败" in caplog.text
    assert "pending=5 errors=0 groups=1" in caplog.text
    assert "RuntimeError" in caplog.text or "disk full" in caplog.text