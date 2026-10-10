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

from .features import all_features, get as feature_get, names as feature_names
from .paths import config_file, env_file

try:  # Python >= 3.11 自带 tomllib
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 兜底
    import tomli as _toml  # type: ignore[no-redef]


class ConfigError(RuntimeError):
    """配置错误：消息面向使用者，应包含修复建议。"""


# 功能开关的**唯一名册**在 src/core/features.py（`/config`、事件中枢门控、/帮助 都用它）。
# 这里只做派生，别再手写第二份——曾经的两份名册导致 /版本 显示 7 个开关、/config 只列 3 个。
_DEFAULT_FEATURES: dict[str, bool] = {item.name: item.default for item in all_features()}

_DEFAULT_PERSONA_NAME = "Yulia"
_DEFAULT_PERSONA_TITLE = "ACT 动漫社助理"
_DEFAULT_PERSONA_ALIASES = ("尤莉娅", "尤莉", "小尤")

_DEFAULT_WELCOME_TEXT = (
    "欢迎 {nickname} 加入 ACT 动漫社！我是社团助理 {bot_name}，先看看群公告，有问题随时在群里问～"
)

_DEFAULT_MODERATION_WARN_TEXT = (
    "{nickname}，请注意群规：{reason}（累计 {count} 次，达到 {limit} 次将禁言）"
)
_DEFAULT_MODERATION_ACTIONS = ("warn", "recall_only", "mute", "kick")


@dataclass(frozen=True)
class PushSchedule:
    """一条定时推送（来自 config.toml 的 ``[[push]]``；执行逻辑见 src/core/push.py）。"""

    name: str
    text: str
    times: tuple[tuple[int, int], ...] = ()
    weekdays: tuple[int, ...] = ()
    targets: tuple[str, ...] = ("admins",)
    feature: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class AppSettings:
    """应用设置（只读快照）。"""

    timezone: str = "Asia/Shanghai"
    bootstrap_admin_qq: str = ""
    protocol_ws_url: str = ""
    protocol_token: str = ""
    features: dict[str, bool] = field(default_factory=lambda: dict(_DEFAULT_FEATURES))
    persona_name: str = _DEFAULT_PERSONA_NAME
    persona_title: str = _DEFAULT_PERSONA_TITLE
    persona_aliases: tuple[str, ...] = _DEFAULT_PERSONA_ALIASES
    welcome_text: str = _DEFAULT_WELCOME_TEXT
    welcome_at_newcomer: bool = True
    broadcast_interval_seconds: float = 3.0
    chat_reply_probability: float = 0.6
    chat_cooldown_seconds: float = 20.0
    chat_escalate_after: int = 3
    chat_escalate_window_seconds: float = 120.0
    stats_flush_seconds: float = 60.0
    stats_top_users: int = 5
    stats_trend_days: int = 7
    stats_range_max_days: int = 90
    stats_digest_at: str = "09:00"
    backup_daily_at: str = "03:00"
    backup_keep_daily_days: int = 30
    backup_keep_monthly: int = 6
    # 群风控（[moderation]）
    moderation_flood_window_seconds: float = 8.0
    moderation_flood_max_messages: int = 8
    moderation_flood_action: str = "mute"
    moderation_flood_mute_seconds: int = 600
    moderation_duplicate_window_seconds: float = 30.0
    moderation_duplicate_max: int = 3
    moderation_duplicate_action: str = "warn"
    moderation_mention_all_action: str = "warn"
    moderation_warn_before_mute: int = 3
    moderation_strike_window_seconds: float = 600.0
    moderation_action_cooldown_seconds: float = 30.0
    moderation_default_mute_seconds: int = 600
    moderation_max_mute_seconds: int = 2592000
    moderation_exempt_group_admins: bool = True
    moderation_dry_run: bool = False
    moderation_warn_text: str = _DEFAULT_MODERATION_WARN_TEXT
    # 内置敏感词库（houbb/sensitive-word-data，见 src/core/wordlists/）
    moderation_sensitive_dict: bool = True
    moderation_sensitive_action: str = "warn"
    moderation_sensitive_skip: bool = False
    moderation_sensitive_min_length: int = 2
    moderation_sensitive_traditional: bool = True
    moderation_sensitive_pinyin: bool = False
    moderation_sensitive_patterns: bool = True
    moderation_sensitive_pattern_action: str = "warn"
    # 定时推送（config.toml 的 [[push]]；见 src/core/push.py）
    pushes: tuple[PushSchedule, ...] = ()
    # 协议端被踢下线后、重新上线时私聊管理员（[alert]；见 src/core/uplink.py）
    alert_uplink: bool = True

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


WEEKDAY_NAMES: tuple[str, ...] = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

_WEEKDAY_ALIASES: dict[str, int] = {
    "mon": 0, "monday": 0, "周一": 0, "星期一": 0,
    "tue": 1, "tuesday": 1, "周二": 1, "星期二": 1,
    "wed": 2, "wednesday": 2, "周三": 2, "星期三": 2,
    "thu": 3, "thursday": 3, "周四": 3, "星期四": 3,
    "fri": 4, "friday": 4, "周五": 4, "星期五": 4,
    "sat": 5, "saturday": 5, "周六": 5, "星期六": 5,
    "sun": 6, "sunday": 6, "周日": 6, "周天": 6, "星期日": 6, "星期天": 6,
}

_TARGET_ADMINS = "admins"
_TARGET_ALL = "all"


def parse_weekdays(value: Any, *, where: str = "weekdays") -> tuple[int, ...]:
    """解析星期数组（mon..sun / 周一..周日）；空数组表示每天。"""
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f'{where} 应为字符串数组，如 ["mon", "wed"] 或 ["周一", "周三"]')
    days: list[int] = []
    for item in value:
        key = item.strip().lower()
        if key not in _WEEKDAY_ALIASES:
            raise ConfigError(f"{where} 含无法识别的星期 {item!r}（可用 mon..sun 或 周一..周日）")
        day = _WEEKDAY_ALIASES[key]
        if day not in days:
            days.append(day)
    return tuple(sorted(days))


def _parse_pushes(raw: Any) -> tuple[PushSchedule, ...]:
    """解析 ``[[push]]`` 数组；配置错误抛出 :class:`ConfigError`。"""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("[[push]] 应为数组（TOML 里写成 [[push]] 段落）")
    schedules: list[PushSchedule] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw, start=1):
        label = f"[[push]] 第 {index} 条"
        if not isinstance(entry, dict):
            raise ConfigError(f"{label}格式错误：应为键值对")
        name = str(entry.get("name", "")).strip()
        if not name:
            raise ConfigError(f"{label}缺少 name（用于日志与 /推送 列表）")
        if name in seen:
            raise ConfigError(f"推送名称重复：{name!r}（name 需唯一）")
        seen.add(name)
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ConfigError(f"{label}「{name}」缺少 text（推送内容）")

        raw_at = entry.get("at")
        if isinstance(raw_at, str):
            at_items: list[Any] = [raw_at]
        elif isinstance(raw_at, list) and raw_at:
            at_items = list(raw_at)
        else:
            raise ConfigError(
                f'{label}「{name}」缺少 at（格式 HH:MM，或 ["08:00", "20:00"]）'
            )
        times: list[tuple[int, int]] = []
        for item in at_items:
            if not isinstance(item, str):
                raise ConfigError(f"{label}「{name}」的 at 里含非字符串：{item!r}")
            moment = parse_hhmm(item)
            if moment not in times:
                times.append(moment)

        weekdays = parse_weekdays(entry.get("weekdays", []), where=f"{label}「{name}」的 weekdays")

        raw_targets = entry.get("targets")
        if raw_targets is None:
            targets = (_TARGET_ADMINS,)
        elif isinstance(raw_targets, list) and raw_targets:
            cleaned: list[str] = []
            for item in raw_targets:
                token = str(item).strip()
                if not token:
                    raise ConfigError(f"{label}「{name}」的 targets 里含空值")
                cleaned.append(token)
            targets = tuple(dict.fromkeys(cleaned))
        else:
            raise ConfigError(
                f'{label}「{name}」的 targets 应为非空数组（"admins" / "all" / 群号）'
            )

        feature = str(entry.get("feature", "") or "").strip().lower()
        if feature and feature_get(feature) is None:
            raise ConfigError(
                f"{label}「{name}」的 feature 未登记：{feature!r}"
                f"（可用 {', '.join(feature_names())}）"
            )
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"{label}「{name}」的 enabled 应为 true / false")

        schedules.append(
            PushSchedule(
                name=name,
                text=text,
                times=tuple(sorted(times)),
                weekdays=weekdays,
                targets=targets,
                feature=feature,
                enabled=enabled,
            )
        )
    return tuple(schedules)


def _mod_action(value: Any, key: str) -> str:
    """校验风控动作名。"""
    text = str(value).strip().lower()
    if text not in _DEFAULT_MODERATION_ACTIONS:
        raise ConfigError(
            "[moderation].{0} 只能是 {1}".format(key, "/".join(_DEFAULT_MODERATION_ACTIONS))
        )
    return text


def _mod_number(value: Any, key: str, *, integer: bool = False, minimum: float = 0.0):
    """校验风控阈值：数字 / 整数 / 下限。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError("[moderation].{0} 应为数字".format(key))
    if integer and not isinstance(value, int):
        raise ConfigError("[moderation].{0} 应为整数".format(key))
    if float(value) < minimum:
        raise ConfigError("[moderation].{0} 应 >= {1:g}".format(key, minimum))
    return int(value) if integer else float(value)


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

    persona = raw.get("persona", {})
    if not isinstance(persona, dict):
        raise ConfigError("[persona] 段落格式错误：应为键值对")
    persona_name = persona.get("name", _DEFAULT_PERSONA_NAME)
    if not isinstance(persona_name, str) or not persona_name.strip():
        raise ConfigError("[persona].name 应为非空字符串")
    persona_title = persona.get("title", _DEFAULT_PERSONA_TITLE)
    if not isinstance(persona_title, str) or not persona_title.strip():
        raise ConfigError("[persona].title 应为非空字符串")
    raw_aliases = persona.get("aliases", list(_DEFAULT_PERSONA_ALIASES))
    if not isinstance(raw_aliases, list) or not all(
        isinstance(item, str) and item.strip() for item in raw_aliases
    ):
        raise ConfigError("[persona].aliases 应为非空字符串数组")
    # 人设名本身也算一个称呼（去重且排在首位）
    persona_aliases = tuple(
        dict.fromkeys([persona_name.strip(), *[item.strip() for item in raw_aliases]])
    )

    welcome = raw.get("welcome", {})
    if not isinstance(welcome, dict):
        raise ConfigError("[welcome] 段落格式错误：应为键值对")
    welcome_text = welcome.get("text", _DEFAULT_WELCOME_TEXT)
    if not isinstance(welcome_text, str) or not welcome_text.strip():
        raise ConfigError("[welcome].text 应为非空字符串")
    welcome_at_newcomer = welcome.get("at_newcomer", True)
    if not isinstance(welcome_at_newcomer, bool):
        raise ConfigError("[welcome].at_newcomer 应为 true / false")

    broadcast = raw.get("broadcast", {})
    interval = broadcast.get("interval_seconds", 3)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval < 0:
        raise ConfigError("[broadcast].interval_seconds 应为非负数字")

    chat = raw.get("chat", {})
    if not isinstance(chat, dict):
        raise ConfigError("[chat] 段落格式错误：应为键值对")
    chat_probability = chat.get("reply_probability", 0.6)
    if isinstance(chat_probability, bool) or not isinstance(chat_probability, (int, float)):
        raise ConfigError("[chat].reply_probability 应为 0-1 之间的数字")
    if not 0 <= float(chat_probability) <= 1:
        raise ConfigError("[chat].reply_probability 应在 0-1 之间")
    chat_cooldown = chat.get("cooldown_seconds", 20)
    if isinstance(chat_cooldown, bool) or not isinstance(chat_cooldown, (int, float)) or chat_cooldown < 0:
        raise ConfigError("[chat].cooldown_seconds 应为非负数字")
    chat_escalate = chat.get("escalate_after", 3)
    if isinstance(chat_escalate, bool) or not isinstance(chat_escalate, int) or chat_escalate < 2:
        raise ConfigError("[chat].escalate_after 应为 >= 2 的整数")
    chat_window = chat.get("escalate_window_seconds", 120)
    if isinstance(chat_window, bool) or not isinstance(chat_window, (int, float)) or chat_window < 0:
        raise ConfigError("[chat].escalate_window_seconds 应为非负数字")

    stats_cfg = raw.get("stats", {})
    if not isinstance(stats_cfg, dict):
        raise ConfigError("[stats] 段落格式错误：应为键值对")
    stats_flush = stats_cfg.get("flush_seconds", 60)
    if isinstance(stats_flush, bool) or not isinstance(stats_flush, (int, float)) or stats_flush <= 0:
        raise ConfigError("[stats].flush_seconds 应为正数")
    stats_top = stats_cfg.get("top_users", 5)
    if isinstance(stats_top, bool) or not isinstance(stats_top, int) or stats_top < 0:
        raise ConfigError("[stats].top_users 应为非负整数")
    stats_trend = stats_cfg.get("trend_days", 7)
    if isinstance(stats_trend, bool) or not isinstance(stats_trend, int) or stats_trend < 1:
        raise ConfigError("[stats].trend_days 应为 >= 1 的整数")
    stats_range_max = stats_cfg.get("range_max_days", 90)
    if isinstance(stats_range_max, bool) or not isinstance(stats_range_max, int) or stats_range_max < 1:
        raise ConfigError("[stats].range_max_days 应为 >= 1 的整数")
    # 每日简报时间：HH:MM；off / none / disable / 空串 表示不发
    stats_digest_at = str(stats_cfg.get("digest_at", "09:00")).strip()
    if stats_digest_at.lower() in ("off", "none", "disable", "disabled"):
        stats_digest_at = ""
    elif stats_digest_at:
        parse_hhmm(stats_digest_at)

    backup = raw.get("backup", {})
    daily_at = str(backup.get("daily_at", "03:00"))
    parse_hhmm(daily_at)  # 提前校验：配置错误立即暴露
    keep_daily = backup.get("keep_daily_days", 30)
    keep_monthly = backup.get("keep_monthly", 6)
    for label, value in (("keep_daily_days", keep_daily), ("keep_monthly", keep_monthly)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigError(f"[backup].{label} 应为非负整数")

    moderation = raw.get("moderation", {})
    if not isinstance(moderation, dict):
        raise ConfigError("[moderation] 段落格式错误：应为键值对")
    mod_flood_window = _mod_number(moderation.get("flood_window_seconds", 8), "flood_window_seconds", minimum=0.1)
    mod_flood_max = _mod_number(moderation.get("flood_max_messages", 8), "flood_max_messages", integer=True, minimum=1)
    mod_flood_action = _mod_action(moderation.get("flood_action", "mute"), "flood_action")
    mod_flood_mute = _mod_number(moderation.get("flood_mute_seconds", 600), "flood_mute_seconds", integer=True)
    mod_dup_window = _mod_number(moderation.get("duplicate_window_seconds", 30), "duplicate_window_seconds", minimum=0.1)
    mod_dup_max = _mod_number(moderation.get("duplicate_max", 3), "duplicate_max", integer=True, minimum=2)
    mod_dup_action = _mod_action(moderation.get("duplicate_action", "warn"), "duplicate_action")
    mod_mention_all = _mod_action(moderation.get("mention_all_action", "warn"), "mention_all_action")
    mod_warn_before = _mod_number(moderation.get("warn_before_mute", 3), "warn_before_mute", integer=True, minimum=1)
    mod_strike_window = _mod_number(moderation.get("strike_window_seconds", 600), "strike_window_seconds")
    mod_action_cd = _mod_number(moderation.get("action_cooldown_seconds", 30), "action_cooldown_seconds")
    mod_default_mute = _mod_number(moderation.get("default_mute_seconds", 600), "default_mute_seconds", integer=True)
    mod_max_mute = _mod_number(moderation.get("max_mute_seconds", 2592000), "max_mute_seconds", integer=True)
    mod_exempt = moderation.get("exempt_group_admins", True)
    if not isinstance(mod_exempt, bool):
        raise ConfigError("[moderation].exempt_group_admins 应为 true / false")
    mod_dry_run = moderation.get("dry_run", False)
    if not isinstance(mod_dry_run, bool):
        raise ConfigError("[moderation].dry_run 应为 true / false")
    mod_warn_text = moderation.get("warn_text", _DEFAULT_MODERATION_WARN_TEXT)
    if not isinstance(mod_warn_text, str) or not mod_warn_text.strip():
        raise ConfigError("[moderation].warn_text 应为非空字符串")
    mod_sensitive_dict = moderation.get("sensitive_dict", True)
    if not isinstance(mod_sensitive_dict, bool):
        raise ConfigError("[moderation].sensitive_dict 应为 true / false")
    mod_sensitive_action = _mod_action(moderation.get("sensitive_action", "warn"), "sensitive_action")
    mod_sensitive_skip = moderation.get("sensitive_skip", False)
    if not isinstance(mod_sensitive_skip, bool):
        raise ConfigError("[moderation].sensitive_skip 应为 true / false")
    mod_sensitive_min = _mod_number(
        moderation.get("sensitive_min_length", 2), "sensitive_min_length", integer=True, minimum=1
    )
    mod_sensitive_traditional = moderation.get("sensitive_traditional", True)
    if not isinstance(mod_sensitive_traditional, bool):
        raise ConfigError("[moderation].sensitive_traditional 应为 true / false")
    mod_sensitive_pinyin = moderation.get("sensitive_pinyin", False)
    if not isinstance(mod_sensitive_pinyin, bool):
        raise ConfigError("[moderation].sensitive_pinyin 应为 true / false")
    mod_sensitive_patterns = moderation.get("sensitive_patterns", True)
    if not isinstance(mod_sensitive_patterns, bool):
        raise ConfigError("[moderation].sensitive_patterns 应为 true / false")
    mod_pattern_action = _mod_action(
        moderation.get("sensitive_pattern_action", "warn"), "sensitive_pattern_action"
    )

    alert = raw.get("alert", {})
    if not isinstance(alert, dict):
        raise ConfigError("[alert] 段落格式错误：应为键值对")
    alert_uplink = alert.get("uplink", True)
    if not isinstance(alert_uplink, bool):
        raise ConfigError("[alert].uplink 应为 true / false")

    pushes = _parse_pushes(raw.get("push"))

    return AppSettings(
        timezone=str(env.get("ACTBOT_TIMEZONE", "Asia/Shanghai")).strip() or "Asia/Shanghai",
        bootstrap_admin_qq=str(env.get("ACTBOT_BOOTSTRAP_ADMIN_QQ", "")).strip(),
        protocol_ws_url=str(env.get("ACTBOT_PROTOCOL_WS_URL", "")).strip(),
        protocol_token=str(env.get("ACTBOT_PROTOCOL_TOKEN", "")).strip(),
        features=features,
        persona_name=persona_name.strip(),
        persona_title=persona_title.strip(),
        persona_aliases=persona_aliases,
        welcome_text=welcome_text,
        welcome_at_newcomer=welcome_at_newcomer,
        broadcast_interval_seconds=float(interval),
        chat_reply_probability=float(chat_probability),
        chat_cooldown_seconds=float(chat_cooldown),
        chat_escalate_after=int(chat_escalate),
        chat_escalate_window_seconds=float(chat_window),
        stats_flush_seconds=float(stats_flush),
        stats_top_users=int(stats_top),
        stats_trend_days=int(stats_trend),
        stats_range_max_days=int(stats_range_max),
        stats_digest_at=stats_digest_at,
        backup_daily_at=daily_at,
        backup_keep_daily_days=int(keep_daily),
        backup_keep_monthly=int(keep_monthly),
        moderation_flood_window_seconds=float(mod_flood_window),
        moderation_flood_max_messages=int(mod_flood_max),
        moderation_flood_action=mod_flood_action,
        moderation_flood_mute_seconds=int(mod_flood_mute),
        moderation_duplicate_window_seconds=float(mod_dup_window),
        moderation_duplicate_max=int(mod_dup_max),
        moderation_duplicate_action=mod_dup_action,
        moderation_mention_all_action=mod_mention_all,
        moderation_warn_before_mute=int(mod_warn_before),
        moderation_strike_window_seconds=float(mod_strike_window),
        moderation_action_cooldown_seconds=float(mod_action_cd),
        moderation_default_mute_seconds=int(mod_default_mute),
        moderation_max_mute_seconds=int(mod_max_mute),
        moderation_exempt_group_admins=mod_exempt,
        moderation_dry_run=mod_dry_run,
        moderation_warn_text=mod_warn_text,
        moderation_sensitive_dict=mod_sensitive_dict,
        moderation_sensitive_action=mod_sensitive_action,
        moderation_sensitive_skip=mod_sensitive_skip,
        moderation_sensitive_min_length=int(mod_sensitive_min),
        moderation_sensitive_traditional=mod_sensitive_traditional,
        moderation_sensitive_pinyin=mod_sensitive_pinyin,
        moderation_sensitive_patterns=mod_sensitive_patterns,
        moderation_sensitive_pattern_action=mod_pattern_action,
        pushes=pushes,
        alert_uplink=alert_uplink,
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
