"""功能注册表：群级功能开关的唯一名册。

`/config`、事件中枢的门控、后续统计都以此为准，避免各处硬编码功能名。
新增功能的流程：
1. 在这里登记一个 :class:`Feature`；
2. 在插件里 `subscribe(SomeEvent, feature=...)`；
3. 群的开关由 `/config <name> on|off` 写进 `groups.features`，无需改代码。
"""
from __future__ import annotations

from dataclasses import dataclass

FEATURE_WELCOME = "welcome"
FEATURE_CHAT = "chat"
FEATURE_STATS = "stats"


@dataclass(frozen=True)
class Feature:
    """一个可开关的功能。

    ``default`` 是"群没有显式设置过"时的取值：默认开启的功能对新群即生效，
    默认关闭的功能（如聊天互动）需要管理员显式打开。
    """

    name: str
    label: str
    default: bool
    description: str = ""


_REGISTRY: tuple[Feature, ...] = (
    Feature(FEATURE_WELCOME, "入群欢迎", True, "有人入群时 @ 新人并发送欢迎语"),
    Feature(FEATURE_CHAT, "聊天互动", False, "关键词/规则触发的轻量互动（尚未实现）"),
    Feature(FEATURE_STATS, "统计", True, "消息量/活跃度计数（尚未实现）"),
)
_BY_NAME = {item.name: item for item in _REGISTRY}


def all_features() -> tuple[Feature, ...]:
    """全部已登记功能（顺序稳定，供 /config 展示）。"""
    return _REGISTRY


def get(name: str) -> Feature | None:
    """按名字取功能；未登记返回 None（调用方据此拒绝非法参数）。"""
    return _BY_NAME.get(str(name).strip().lower())


def names() -> tuple[str, ...]:
    """全部功能名。"""
    return tuple(item.name for item in _REGISTRY)


def default_of(name: str, *, fallback: bool = True) -> bool:
    """功能的默认开关；未登记的功能回退为 ``fallback``。"""
    item = get(name)
    return item.default if item is not None else fallback

