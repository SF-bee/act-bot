"""跨平台路径解析：所有文件路径统一从这里获取，禁止散落硬编码。

约定：
- 仓库根 = 本文件的上两级目录（src/core/paths.py → 仓库根）
- 数据目录 = 环境变量 ``ACTBOT_DATA_DIR``（相对路径以仓库根为基准；默认 ``data``）
- 任何模块需要路径时，调用本模块函数，不要自己拼接字符串
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


def project_root() -> Path:
    """仓库根目录。"""
    return PROJECT_ROOT


def get_data_dir() -> Path:
    """数据目录（``ACTBOT_DATA_DIR`` 优先；相对路径以仓库根为基准）。"""
    raw = os.environ.get("ACTBOT_DATA_DIR", "data").strip() or "data"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def db_path() -> Path:
    """数据库文件（唯一资产之一）。"""
    return get_data_dir() / "act.db"


def uploads_dir() -> Path:
    """附件目录（作品/资料文件）。"""
    return get_data_dir() / "uploads"


def backups_dir() -> Path:
    """备份目录。"""
    return get_data_dir() / "backups"


def config_file() -> Path:
    """业务配置文件位置（可能不存在）。"""
    return PROJECT_ROOT / "config" / "config.toml"


def env_file() -> Path:
    """部署配置文件位置（可能不存在）。"""
    return PROJECT_ROOT / ".env"


def ensure_dir(path: Path) -> Path:
    """创建目录（含父级）并返回之。"""
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_path_inside(child: Path, parent: Path) -> bool:
    """判断 ``child`` 是否位于 ``parent`` 内（跨平台实现，用于安全校验）。"""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
