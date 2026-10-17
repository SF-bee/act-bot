"""manage.py 的 owner 保护（子进程运行，避免干扰当前测试引擎）。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manage_rejects_owner_role(temp_data_dir):
    env = {**os.environ, "ACTBOT_DATA_DIR": str(temp_data_dir)}
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "manage.py"),
            "admins",
            "add",
            "123456789",
            "--role",
            "owner",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    assert result.returncode == 1, result.stderr
    assert "--role owner 已禁用" in result.stderr
    assert "bootstrap_admin.py" in result.stderr
