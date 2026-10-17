"""调度器任务注册：单个任务配置坏了只跳过它，不影响其它任务。"""
from __future__ import annotations

import dataclasses

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.core import config, scheduler as sched


def _settings(tmp_path, **overrides):
    settings = config.load_settings(
        env={}, toml_path=tmp_path / "missing.toml", load_dotenv_first=False
    )
    return dataclasses.replace(settings, **overrides)


def test_registers_default_jobs(tmp_path):
    scheduler = AsyncIOScheduler()
    ids = sched._register_jobs(scheduler, _settings(tmp_path))
    assert "daily-backup" in ids
    assert "stats-flush" in ids
    assert "stats-digest" in ids


def test_bad_backup_time_does_not_skip_other_jobs(tmp_path):
    scheduler = AsyncIOScheduler()
    ids = sched._register_jobs(scheduler, _settings(tmp_path, backup_daily_at="not-a-time"))
    assert "daily-backup" not in ids
    assert "stats-flush" in ids
    assert "stats-digest" in ids


def test_bad_digest_time_keeps_flush(tmp_path):
    scheduler = AsyncIOScheduler()
    ids = sched._register_jobs(scheduler, _settings(tmp_path, stats_digest_at="99:99"))
    assert "stats-digest" not in ids
    assert "stats-flush" in ids
    assert "daily-backup" in ids


def test_stats_feature_off_skips_stats_jobs(tmp_path):
    settings = _settings(tmp_path)
    settings.features["stats"] = False
    scheduler = AsyncIOScheduler()
    ids = sched._register_jobs(scheduler, settings)
    assert "stats-flush" not in ids
    assert "stats-digest" not in ids
    assert "daily-backup" in ids