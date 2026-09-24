"""pytest 共享夹具：隔离数据目录 + 干净数据库（跨平台）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def temp_data_dir(tmp_path, monkeypatch):
    """把数据目录切到临时目录，避免测试触碰真实 data/。"""
    data = tmp_path / "data"
    monkeypatch.setenv("ACTBOT_DATA_DIR", str(data))
    from src.core import config

    config.reset_settings_cache()
    yield data
    config.reset_settings_cache()


@pytest.fixture()
async def fresh_db(temp_data_dir):
    """初始化一个干净数据库；测试结束后关闭引擎。"""
    from src.core import db

    await db.init_db()
    yield db
    await db.dispose_engine()
