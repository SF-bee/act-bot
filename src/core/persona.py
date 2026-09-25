"""机器人人设（对外身份）。

**人设名与技术名刻意分开**：
- 技术名 `act-bot` 出现在仓库名、服务名、日志 logger、部署文档里；
- 人设名（默认 **Yulia｜ACT 动漫社助理**）出现在群里说的话、`/help`、`/version`、欢迎语里。

名字 / 身份 / 别名都在 `config/config.toml` 的 `[persona]` 配置，改完重启业务层生效。
别名用于判断"群友是否在叫它"（聊天引擎/唤醒用），见 :func:`is_called`。
"""
from __future__ import annotations

from typing import Sequence

from src.core.config import get_settings


def alias_matches(text: str, aliases: Sequence[str]) -> bool:
    """文本里是否出现任一别名（大小写不敏感）。纯函数，便于测试。"""
    haystack = (text or "").casefold()
    return any(alias.casefold() in haystack for alias in aliases if alias)


def format_intro(name: str, title: str, *, separator: str = "｜") -> str:
    """一行自我介绍：``Yulia｜ACT 动漫社助理``（缺项自动省略）。"""
    parts = [part.strip() for part in (name, title) if part and part.strip()]
    return separator.join(parts)


def name() -> str:
    """人设名（默认 Yulia）。"""
    return get_settings().persona_name


def title() -> str:
    """人设身份（默认 ACT 动漫社助理）。"""
    return get_settings().persona_title


def aliases() -> tuple[str, ...]:
    """群友可能的称呼（含人设名本身）。"""
    return tuple(get_settings().persona_aliases)


def intro() -> str:
    """一行自我介绍（对外文案统一用这个）。"""
    return format_intro(name(), title())


def is_called(text: str) -> bool:
    """消息里是否在叫它。

    目前是子串匹配（够用且可预期）；将来若需要"只认独立称呼"，在这里加边界规则即可，
    调用方（聊天引擎）不用改。
    """
    return alias_matches(text, aliases())

