"""聊天引擎：确定性机制（关键词 / 正则 / @ 回复池 + 状态机 + 冷却），不接 LLM。

分层：
- **纯逻辑**（可单测）：命中匹配、加权随机选取、档位（连续被叫）、概率、冷却判断；
- **状态**：进程内存（群 + 人 维度），重启即清空——不做长期画像、不落库；
- **规则**：SQLite ``chat_rules`` 表，群级规则覆盖同 kind 的全局规则（见 :func:`pool_for`）。

档位（简单状态机）：短时间内连续被叫 → mention → mention_more → mention_tired，
缺档自动回退到上一档（管理员不必把每一档都填满）。
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from sqlalchemy import select

from src.core import db
from src.core.db import utc_now
from src.core.persona import name as persona_name, title as persona_title
from src.models.tables import ChatRule

KIND_KEYWORD = "keyword"
KIND_REGEX = "regex"
KIND_MENTION = "mention"
KIND_MENTION_MORE = "mention_more"
KIND_MENTION_TIRED = "mention_tired"

VALID_KINDS = (KIND_KEYWORD, KIND_REGEX, KIND_MENTION, KIND_MENTION_MORE, KIND_MENTION_TIRED)
# 被叫档位：第 1 档常规，第 2 档「又叫我」，第 3 档起「被叫烦了」
MENTION_LADDER = (KIND_MENTION, KIND_MENTION_MORE, KIND_MENTION_TIRED)

CHAT_ACTIONS = ("list", "add", "del")


@dataclass(frozen=True)
class Rule:
    """一条聊天规则（数据库行的轻量视图）。"""

    id: int = 0
    group_id: str = ""
    kind: str = KIND_KEYWORD
    pattern: str = ""
    reply: str = ""
    weight: int = 1
    enabled: bool = True


@dataclass(frozen=True)
class Decision:
    """一次聊天的决策结果（回复为空表示不回应）。"""

    reply: str | None
    reason: str
    rule: Rule | None = None


# ---------- 命令解析（纯函数） ----------


def parse_chat_command(text: str) -> tuple[str, list[str]]:
    """解析 ``/chat`` 子命令，返回 ``(action, args)``。

    action：``""``（看状态）、``list``、``add``、``del``、``unknown``。
    """
    parts = text.strip().split()
    if len(parts) < 2:
        return "", []
    action = parts[1].strip().lower()
    if action not in CHAT_ACTIONS:
        return "unknown", parts[2:]
    return action, parts[2:]


def parse_add_args(args: Sequence[str]) -> tuple[str, str, str, str]:
    """解析 ``add`` 参数，返回 ``(scope, kind, pattern, reply)``。

    两种形状：
    - ``[-g] <kind> <触发词> <回复…>``：keyword / regex 需要触发词；
    - ``[-g] <kind> <回复…>``：mention / mention_more / mention_tired 不需要触发词。

    ``scope`` 为 ``group`` 或 ``global``；不合法时 ``kind`` 返回空串。
    """
    items = list(args)
    scope = "group"
    if items and items[0] == "-g":
        scope = "global"
        items = items[1:]
    if not items:
        return scope, "", "", ""
    kind = items[0].strip().lower()
    if kind not in VALID_KINDS:
        return scope, "", "", ""
    if kind in (KIND_MENTION, KIND_MENTION_MORE, KIND_MENTION_TIRED):
        return scope, kind, "", " ".join(items[1:]).strip()
    if len(items) < 3:
        return scope, "", "", ""
    return scope, kind, items[1].strip(), " ".join(items[2:]).strip()


# ---------- 匹配与选取（纯函数） ----------


def pool_for(rules: Iterable[Rule], group_id: str, kind: str) -> list[Rule]:
    """取某个 kind 的候选池：群级规则优先；该群没有则回退全局规则。"""
    enabled = [rule for rule in rules if rule.enabled and rule.kind == kind]
    gid = str(group_id)
    group_pool = [rule for rule in enabled if rule.group_id == gid]
    if group_pool:
        return group_pool
    return [rule for rule in enabled if rule.group_id == ""]


def match_rules(rules: Iterable[Rule], text: str) -> list[Rule]:
    """命中普通触发（keyword 子串 / regex）：返回所有命中的规则。"""
    matched: list[Rule] = []
    haystack = text or ""
    lowered = haystack.casefold()
    for rule in rules:
        if not rule.enabled or not rule.pattern:
            continue
        if rule.kind == KIND_KEYWORD:
            if rule.pattern.casefold() in lowered:
                matched.append(rule)
        elif rule.kind == KIND_REGEX:
            try:
                if re.search(rule.pattern, haystack):
                    matched.append(rule)
            except re.error:
                continue  # 非法正则：跳过该规则，不让它拖垮整条链路
    return matched


def pick_weighted(rules: Sequence[Rule], rng: random.Random | None = None) -> Rule | None:
    """按 weight 加权随机选一条；权重全 <= 0 时退回均匀随机。"""
    if not rules:
        return None
    picker = rng or random
    weights = [max(0, int(rule.weight)) for rule in rules]
    total = sum(weights)
    if total <= 0:
        return rules[picker.randrange(len(rules))]
    point = picker.uniform(0, total)
    upto = 0.0
    for rule, weight in zip(rules, weights):
        upto += weight
        if point <= upto:
            return rule
    return rules[-1]


def mention_level(streak: int, *, escalate_after: int = 3) -> int:
    """连续被叫的第 ``streak`` 次对应哪个档位（1 起）。"""
    threshold = max(2, int(escalate_after))
    if streak <= 1:
        return 1
    if streak < threshold:
        return 2
    return 3


def ladder_kinds(level: int) -> tuple[str, ...]:
    """该档位可用的 kind 及缺档回退链。"""
    index = min(max(level, 1), len(MENTION_LADDER)) - 1
    return tuple(reversed(MENTION_LADDER[: index + 1]))


def render_reply(template: str, *, user_id: str, nickname: str = "", group_name: str = "") -> str:
    """渲染回复里的占位符（未知占位符原样保留）。"""
    replacements = (
        ("user_id", user_id),
        ("nickname", nickname or user_id),
        ("group_name", group_name),
        ("bot_name", persona_name()),
        ("bot_title", persona_title()),
    )
    text = template
    for key, value in replacements:
        text = text.replace("{" + key + "}", value)
    return text


# ---------- 进程内状态（cooldown + 连续被叫） ----------


class ChatState:
    """内存状态：谁刚刚被回过、谁在连续叫它。重启即清空。"""

    def __init__(self) -> None:
        self._last_reply: dict[tuple[str, str], float] = {}
        self._mention: dict[tuple[str, str], tuple[int, float]] = {}

    def allow(self, group_id: str, user_id: str, *, now: float, cooldown: float) -> bool:
        """距离上次回复是否已过冷却。"""
        if cooldown <= 0:
            return True
        last = self._last_reply.get((str(group_id), str(user_id)))
        return last is None or now - last >= cooldown

    def mark_replied(self, group_id: str, user_id: str, *, now: float) -> None:
        key = (str(group_id), str(user_id))
        self._last_reply[key] = now
        if len(self._last_reply) > 2048:
            self._last_reply = {key: stamp for key, stamp in self._last_reply.items() if stamp > now - 3600}

    def mention_streak(self, group_id: str, user_id: str, *, now: float, window: float) -> int:
        """记一次「被叫」，返回窗口内连续次数（超过窗口则重置为 1）。"""
        key = (str(group_id), str(user_id))
        count, last = self._mention.get(key, (0, 0.0))
        streak = count + 1 if (window > 0 and now - last <= window) else 1
        self._mention[key] = (streak, now)
        if len(self._mention) > 2048:
            self._mention = {
                item: value for item, value in self._mention.items() if now - value[1] <= max(window, 60)
            }
        return streak

    def reset(self) -> None:
        """清空状态（测试用）。"""
        self._last_reply.clear()
        self._mention.clear()


def decide(
    rules: Sequence[Rule],
    *,
    text: str,
    at_self: bool,
    group_id: str,
    user_id: str,
    state: ChatState,
    now: float,
    cooldown: float = 20.0,
    probability: float = 0.6,
    escalate_after: int = 3,
    escalate_window: float = 120.0,
    rng: random.Random | None = None,
) -> Decision:
    """核心决策：被 @ 必回（分档），关键词按概率回；冷却内一律不打扰。"""
    if not state.allow(group_id, user_id, now=now, cooldown=cooldown):
        return Decision(None, "cooled")

    if at_self:
        streak = state.mention_streak(group_id, user_id, now=now, window=escalate_window)
        level = mention_level(streak, escalate_after=escalate_after)
        for kind in ladder_kinds(level):
            pool = pool_for(rules, group_id, kind)
            if pool:
                rule = pick_weighted(pool, rng)
                if rule is None:
                    break
                state.mark_replied(group_id, user_id, now=now)
                return Decision(rule.reply, kind, rule)  # reason = 实际提供回复的档位
        return Decision(None, "no_match")

    matched = match_rules(rules, text)
    if not matched:
        return Decision(None, "no_match")
    picker = rng or random
    ratio = max(0.0, min(1.0, float(probability)))
    if ratio < 1.0 and picker.random() > ratio:
        return Decision(None, "missed")
    rule = pick_weighted(matched, rng)
    if rule is None:
        return Decision(None, "no_match")
    state.mark_replied(group_id, user_id, now=now)
    return Decision(rule.reply, "keyword", rule)


# ---------- 规则存取（数据库） ----------


def _to_rule(row: ChatRule) -> Rule:
    return Rule(
        id=int(row.id),
        group_id=str(row.group_id or ""),
        kind=str(row.kind),
        pattern=str(row.pattern or ""),
        reply=str(row.reply),
        weight=int(row.weight or 1),
        enabled=bool(row.enabled),
    )


async def load_rules(group_id: str) -> list[Rule]:
    """载入某群可用的全部规则（本群 + 全局）。"""
    gid = str(group_id)
    async with db.get_session() as session:
        rows = (
            await session.execute(
                select(ChatRule).where(ChatRule.group_id.in_([gid, ""])).order_by(ChatRule.id)
            )
        ).scalars().all()
    return [_to_rule(row) for row in rows]


async def add_rule(
    kind: str,
    pattern: str,
    reply: str,
    *,
    group_id: str = "",
    weight: int = 1,
    created_by: str = "",
) -> int:
    """新增规则，返回新行 id。"""
    if kind not in VALID_KINDS:
        raise ValueError(f"未知规则类型：{kind!r}")
    async with db.get_session() as session:
        row = ChatRule(
            group_id=str(group_id),
            kind=str(kind),
            pattern=str(pattern),
            reply=str(reply),
            weight=int(weight),
            enabled=1,
            created_by=str(created_by),
            created_at=utc_now(),
        )
        session.add(row)
        await session.commit()
        return int(row.id)


async def delete_rule(rule_id: int, *, group_id: str | None = None) -> bool:
    """删除规则；给了 ``group_id`` 时只允许删本群或全局规则。"""
    async with db.get_session() as session:
        row = (await session.execute(select(ChatRule).where(ChatRule.id == int(rule_id)))).scalar_one_or_none()
        if row is None:
            return False
        if group_id is not None and str(row.group_id) not in (str(group_id), ""):
            return False
        await session.delete(row)
        await session.commit()
        return True


async def list_rules(group_id: str, *, limit: int = 20) -> list[Rule]:
    """本群可用规则（本群在前，含全局），最多 ``limit`` 条。"""
    rules = await load_rules(group_id)
    gid = str(group_id)
    rules.sort(key=lambda rule: (0 if rule.group_id == gid else 1, rule.kind, rule.id))
    return rules[: max(1, int(limit))]

