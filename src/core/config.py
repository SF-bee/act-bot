"""配置加载：部署层（.env / 环境变量）→ 业务层（config/config.toml）→ 运行层（数据库）。

单一来源原则：每个配置项只允许出现在一层。
本模块只负责读取；写入由 ``scripts/`` 或群内命令完成。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import config_file, env_file

try:  # Python >= 3.11 自带 tomllib
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 兜底
    import tomli as _toml  # type: ignore[no-redef]


class ConfigError(RuntimeError):
    """配置错误：消息面向使用者，应包含修复建议。"""


_DEFAULT_FEATURES: dict[str, bool] = {
    "welcome": True,
    "departments": True,
    "events": True,
    "signups": True,
    "broadcast": True,
    "archive": True,
    "group_admin": True,
}


@dataclass(frozen=True)
class AppSettings:
    """应用设置（只读快照）。"""

    timezone: str = "Asia/Shanghai"
    bootstrap_admin_qq: str = ""
    protocol_ws_url: str = ""
    protocol_token: str = ""
    features: dict[str, bool] = field(default_factory=lambda: dict(_DEFAULT_FEATURES))
    broadcast_interval_seconds: float = 3.0
    backup_daily_at: str = "03:00"
    backup_keep_daily_days: int = 30
    backup_keep_monthly: int = 6

    def feature(self, name: str) -> bool:
        """功能开关查询；未定义的开关默认开启。"""
        return bool(self.features.get(name, True))


_load_env_done = False


def load_env_file(path: Path | None = None) -> None:
    """把 .env 加载进环境变量（不覆盖已有变量；无参数时只执行一次）。"""
    global _load_env_done
    if _load_env_done and path is None:
        return
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:  # pragma: no cover - 极端环境缺 dotenv 时静默跳过
        return
    target = path or env_file()
    if target.is_file():
        load_dotenv(target, override=False)
    _load_env_done = True


_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_hhmm(value: str) -> tuple[int, int]:
    """解析 ``HH:MM`` 时间；非法值抛出 :class:`ConfigError`。"""
    match = _HHMM_RE.match(str(value).strip())
    if not match:
        raise ConfigError(f"时间格式应为 HH:MM（当前为 {value!r}）")
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ConfigError(f"时间超出范围（当前为 {value!r}）")
    return hour, minute


def load_settings(
    env: dict[str, str] | None = None,
    toml_path: Path | None = None,
    *,
    load_dotenv_first: bool = True,
) -> AppSettings:
    """从环境变量 + 业务配置装载设置（不缓存；测试可直接调用）。"""
    if load_dotenv_first:
        load_env_file()
    env = dict(os.environ) if env is None else dict(env)

    raw: dict[str, Any] = {}
    path = toml_path if toml_path is not None else config_file()
    if path.is_file():
        try:
            raw = _toml.loads(path.read_text(encoding="utf-8"))
        except _toml.TOMLDecodeError as exc:  # type: ignore[attr-defined]
            raise ConfigError(f"无法解析 {path}：{exc}") from exc

    features = dict(_DEFAULT_FEATURES)
    user_features = raw.get("features", {})
    if not isinstance(user_features, dict):
        raise ConfigError("[features] 段落格式错误：应为键值对")
    for key, value in user_features.items():
        if not isinstance(value, bool):
            raise ConfigError(f"功能开关 {key!r} 应为 true / false")
        features[key] = value

    broadcast = raw.get("broadcast", {})
    interval = broadcast.get("interval_seconds", 3)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval < 0:
        raise ConfigError("[broadcast].interval_seconds 应为非负数字")

    backup = raw.get("backup", {})
    daily_at = str(backup.get("daily_at", "03:00"))
    parse_hhmm(daily_at)  # 提前校验：配置错误立即暴露
    keep_daily = backup.get("keep_daily_days", 30)
    keep_monthly = backup.get("keep_monthly", 6)
    for label, value in (("keep_daily_days", keep_daily), ("keep_monthly", keep_monthly)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigError(f"[backup].{label} 应为非负整数")

    return AppSettings(
        timezone=str(env.get("ACTBOT_TIMEZONE", "Asia/Shanghai")).strip() or "Asia/Shanghai",
        bootstrap_admin_qq=str(env.get("ACTBOT_BOOTSTRAP_ADMIN_QQ", "")).strip(),
        protocol_ws_url=str(env.get("ACTBOT_PROTOCOL_WS_URL", "")).strip(),
        protocol_token=str(env.get("ACTBOT_PROTOCOL_TOKEN", "")).strip(),
        features=features,
        broadcast_interval_seconds=float(interval),
        backup_daily_at=daily_at,
        backup_keep_daily_days=int(keep_daily),
        backup_keep_monthly=int(keep_monthly),
    )


_settings: AppSettings | None = None


def get_settings() -> AppSettings:
    """进程级缓存设置；修改配置后请调用 :func:`reset_settings_cache`。"""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings_cache() -> None:
    """清空设置缓存（测试 / 配置热更新用）。"""
    global _settings
    _settings = None
