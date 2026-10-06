"""群风控：敏感信息撤回/警告、刷屏/复读检测与处置（确定性，不接 AI）。

分层（与 chat.py 一致）：
- 纯逻辑：规则匹配、严重度取最严、刷屏/复读/警告计数、命令解析；
- 状态：进程内存（群 + 人 维度），重启即清空；
- 规则：SQLite moderation_rules 表，全局 + 本群叠加生效。

动作 action：
- warn        警告（累计到 warn_before_mute 次自动升级为禁言）
- recall_only 仅撤回
- mute        撤回 + 禁言
- kick        撤回 + 踢出
严重度 kick > mute > warn > recall_only；一条消息命中多条时取最严。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from sqlalchemy import select

from src.core import db
from src.core.db import utc_now
from src.models.tables import ModerationRule

KIND_KEYWORD = "keyword"
KIND_REGEX = "regex"
VALID_KINDS = (KIND_KEYWORD, KIND_REGEX)

ACTION_WARN = "warn"
ACTION_RECALL_ONLY = "recall_only"
ACTION_MUTE = "mute"
ACTION_KICK = "kick"
VALID_ACTIONS = (ACTION_WARN, ACTION_RECALL_ONLY, ACTION_MUTE, ACTION_KICK)

SEVERITY = {
    ACTION_RECALL_ONLY: 0,
    ACTION_WARN: 1,
    ACTION_MUTE: 2,
    ACTION_KICK: 3,
}

DEFAULT_MUTE_SECONDS = 600
MAX_MUTE_SECONDS = 2592000

MOD_ACTIONS = ("list", "add", "del", "test", "log")

# 内置正则检测的展示名
PATTERN_LABELS = {"url": "网址", "domain": "网址", "phone": "手机号", "qq": "QQ号"}


@dataclass(frozen=True)
class Rule:
    """一条风控规则（数据库行的轻量视图）。"""

    id: int = 0
    group_id: str = ""
    kind: str = KIND_KEYWORD
    pattern: str = ""
    action: str = ACTION_WARN
    recall: bool = True
    mute_seconds: int = DEFAULT_MUTE_SECONDS
    enabled: bool = True
    note: str = ""


@dataclass(frozen=True)
class Violation:
    """一次判定的结果。"""

    kind: str
    reason: str
    action: str = ACTION_WARN
    recall: bool = True
    mute_seconds: int = DEFAULT_MUTE_SECONDS
    rule_id: int = 0
    strike: int = 0


@dataclass(frozen=True)
class Policy:
    """风控阈值（由 config 的 [moderation] 段构造）。"""

    flood_window: float = 8.0
    flood_max: int = 8
    flood_action: str = ACTION_MUTE
    flood_mute_seconds: int = DEFAULT_MUTE_SECONDS
    duplicate_window: float = 30.0
    duplicate_max: int = 3
    duplicate_action: str = ACTION_WARN
    mention_all_action: str = ACTION_WARN
    cooldown: float = 30.0
    default_mute_seconds: int = DEFAULT_MUTE_SECONDS
    max_mute_seconds: int = MAX_MUTE_SECONDS
    warn_before_mute: int = 3
    strike_window: float = 600.0
    # 内置敏感词库
    sensitive_action: str = ACTION_WARN
    sensitive_skip: bool = False
    sensitive_min_length: int = 2
    pattern_action: str = ACTION_WARN


@dataclass(frozen=True)
class AddArgs:
    """解析 /mod add 的结果。"""

    ok: bool = False
    global_scope: bool = False
    recall: bool = True
    kind: str = ""
    pattern: str = ""
    action: str = ACTION_WARN
    mute_seconds: int = 0


# ---------- 纯逻辑 ----------


def fingerprint(text: str, image_ids: Sequence[str] = ()) -> str:
    """消息指纹：有文本用规范化文本，无文本用图片 id 串；空消息返回空串。"""
    normalized = re.sub(r"\s+", "", (text or "").casefold())
    if normalized:
        return normalized
    ids = [str(item) for item in image_ids if str(item)]
    return "|".join(ids)


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
                continue  # 非法正则：跳过该规则，不拖垮链路
    return matched


def pick_severity(violations: Sequence[Violation]) -> Violation | None:
    """取最严动作；同 severity 保留先出现的（稳定）。"""
    best: Violation | None = None
    for item in violations:
        if best is None or SEVERITY.get(item.action, 1) > SEVERITY.get(best.action, 1):
            best = item
    return best


def violations_for_rules(rules: Sequence[Rule], text: str) -> list[Violation]:
    """把命中的规则转成违规项。"""
    out: list[Violation] = []
    for rule in match_rules(rules, text):
        reason = rule.note or ("命中规则 #" + str(rule.id) if rule.id else "命中敏感规则")
        out.append(
            Violation(
                kind="sensitive",
                reason=reason,
                action=rule.action,
                recall=rule.recall,
                mute_seconds=rule.mute_seconds,
                rule_id=rule.id,
            )
        )
    return out


def render_warn(
    template: str,
    *,
    nickname: str = "",
    user_id: str = "",
    reason: str = "",
    count: int = 0,
    limit: int = 0,
    bot_name: str = "",
    bot_title: str = "",
) -> str:
    """渲染警告文案里的占位符（未知占位符原样保留）。"""
    replacements = (
        ("nickname", nickname or user_id),
        ("user_id", user_id),
        ("reason", reason),
        ("count", count),
        ("limit", limit),
        ("bot_name", bot_name),
        ("bot_title", bot_title),
    )
    text = template or ""
    for key, value in replacements:
        text = text.replace("{" + key + "}", str(value))
    return text


def parse_mod_command(tokens: Sequence[str]) -> tuple[str, list[str]]:
    """解析 /mod 的子命令，返回 (action, args)。

    action：""（看状态）/ list / add / del / test / log / unknown。
    """
    items = list(tokens)
    if not items:
        return "", []
    action = items[0].strip().lower()
    if action not in MOD_ACTIONS:
        return "unknown", items[1:]
    return action, items[1:]


def parse_add_args(tokens: Sequence[str]) -> AddArgs:
    """解析 /mod add 参数：[-n] <kind> | <pattern> | <action> | <秒>。

    --global 由调用方在解析前摘除（见插件），这里只处理 -n 与管道分隔。
    """
    items: list[str] = []
    recall = True
    for token in tokens:
        if token == "-n":
            recall = False
            continue
        items.append(token)
    segments: list[list[str]] = []
    current: list[str] = []
    for token in items:
        if token == "|":
            segments.append(current)
            current = []
        else:
            current.append(token)
    segments.append(current)
    if len(segments) < 3:
        return AddArgs()
    kind = " ".join(segments[0]).strip().lower()
    pattern = " ".join(segments[1]).strip()
    action = (" ".join(segments[2]).strip().lower()) or ACTION_WARN
    seconds = 0
    if len(segments) >= 4:
        raw = " ".join(segments[3]).strip()
        if raw:
            if not raw.isdigit():
                return AddArgs()
            seconds = int(raw)
    if kind not in VALID_KINDS or action not in VALID_ACTIONS or not pattern:
        return AddArgs()
    return AddArgs(
        ok=True,
        recall=recall,
        kind=kind,
        pattern=pattern,
        action=action,
        mute_seconds=seconds,
    )


# ---------- 进程内状态（刷屏 / 复读 / 警告 / 冷却） ----------


class ModerationState:
    """内存状态：谁在刷屏、复读了什么、被警告了几次。重启即清空。"""

    def __init__(self) -> None:
        self._flood: dict[tuple[str, str], list[float]] = {}
        self._dup: dict[tuple[str, str], tuple[str, int, float]] = {}
        self._strikes: dict[tuple[str, str], tuple[int, float]] = {}
        self._acted: dict[tuple[str, str], float] = {}

    @staticmethod
    def _key(group_id: str, user_id: str) -> tuple[str, str]:
        return (str(group_id), str(user_id))

    def allow_action(self, group_id: str, user_id: str, *, now: float, cooldown: float) -> bool:
        """距离上次处置是否已过冷却（防止连续处置刷屏）。"""
        if cooldown <= 0:
            return True
        last = self._acted.get(self._key(group_id, user_id))
        return last is None or now - last >= cooldown

    def mark_action(self, group_id: str, user_id: str, *, now: float) -> None:
        key = self._key(group_id, user_id)
        self._acted[key] = now
        if len(self._acted) > 2048:
            self._acted = {
                item: stamp for item, stamp in self._acted.items() if stamp > now - 3600
            }

    def check_flood(
        self, group_id: str, user_id: str, *, now: float, window: float, max_count: int
    ) -> bool:
        """记一条消息，判断窗口内是否超过阈值。"""
        key = self._key(group_id, user_id)
        stamps = [stamp for stamp in self._flood.get(key, []) if now - stamp <= window]
        stamps.append(now)
        self._flood[key] = stamps
        if len(self._flood) > 2048:
            self._flood = {
                item: [s for s in value if now - s <= max(window, 60)]
                for item, value in self._flood.items()
            }
            self._flood = {item: value for item, value in self._flood.items() if value}
        return len(stamps) >= max(1, int(max_count))

    def check_duplicate(
        self,
        group_id: str,
        user_id: str,
        fingerprint_value: str,
        *,
        now: float,
        window: float,
        max_count: int,
    ) -> bool:
        """记一条消息指纹，判断是否在窗口内重复超过阈值。"""
        if not fingerprint_value:
            return False
        key = self._key(group_id, user_id)
        last_fp, count, last_at = self._dup.get(key, ("", 0, 0.0))
        if last_fp == fingerprint_value and now - last_at <= window:
            count += 1
        else:
            count = 1
        self._dup[key] = (fingerprint_value, count, now)
        if len(self._dup) > 2048:
            self._dup = {
                item: value for item, value in self._dup.items() if now - value[2] <= max(window, 60)
            }
        return count >= max(2, int(max_count))

    def bump_strike(self, group_id: str, user_id: str, *, now: float, window: float) -> int:
        """记一次警告，返回窗口内累计次数。"""
        key = self._key(group_id, user_id)
        count, last = self._strikes.get(key, (0, 0.0))
        streak = count + 1 if (window > 0 and now - last <= window) else 1
        self._strikes[key] = (streak, now)
        if len(self._strikes) > 2048:
            self._strikes = {
                item: value
                for item, value in self._strikes.items()
                if now - value[1] <= max(window, 60)
            }
        return streak

    def strike_count(self, group_id: str, user_id: str, *, now: float, window: float) -> int:
        count, last = self._strikes.get(self._key(group_id, user_id), (0, 0.0))
        if window > 0 and now - last > window:
            return 0
        return count

    def reset(self) -> None:
        """清空状态（测试用）。"""
        self._flood.clear()
        self._dup.clear()
        self._strikes.clear()
        self._acted.clear()


def decide(
    *,
    rules: Sequence[Rule],
    text: str,
    image_ids: Sequence[str] = (),
    dict_hits: Sequence[str] = (),
    pinyin_hits: Sequence[str] = (),
    pattern_hits: Sequence[tuple[str, str]] = (),
    at_all: bool = False,
    group_id: str,
    user_id: str,
    state: ModerationState,
    now: float,
    policy: Policy,
) -> Violation | None:
    """核心决策：规则 / 刷屏 / 复读 / @全体 → 取最严 → warn 达阈值升级 mute。"""
    if not state.allow_action(group_id, user_id, now=now, cooldown=policy.cooldown):
        return None

    found: list[Violation] = violations_for_rules(rules, text)
    if dict_hits:
        found.append(
            Violation(
                kind="dict",
                reason="内置敏感词：" + str(dict_hits[0]),
                action=policy.sensitive_action,
                recall=True,
                mute_seconds=policy.default_mute_seconds,
            )
        )
    if pinyin_hits:
        found.append(
            Violation(
                kind="pinyin",
                reason="拼音变体：" + str(pinyin_hits[0]),
                action=policy.sensitive_action,
                recall=True,
                mute_seconds=policy.default_mute_seconds,
            )
        )
    if pattern_hits:
        pattern_kind, pattern_text = pattern_hits[0]
        found.append(
            Violation(
                kind="pattern",
                reason="疑似{0}：{1}".format(
                    PATTERN_LABELS.get(pattern_kind, pattern_kind), pattern_text
                ),
                action=policy.pattern_action,
                recall=True,
                mute_seconds=policy.default_mute_seconds,
            )
        )
    fp = fingerprint(text, image_ids)
    if state.check_duplicate(
        group_id,
        user_id,
        fp,
        now=now,
        window=policy.duplicate_window,
        max_count=policy.duplicate_max,
    ):
        found.append(
            Violation(
                kind="duplicate",
                reason="重复刷屏",
                action=policy.duplicate_action,
                recall=True,
                mute_seconds=policy.default_mute_seconds,
            )
        )
    if state.check_flood(
        group_id,
        user_id,
        now=now,
        window=policy.flood_window,
        max_count=policy.flood_max,
    ):
        found.append(
            Violation(
                kind="flood",
                reason="刷屏",
                action=policy.flood_action,
                recall=False,
                mute_seconds=policy.flood_mute_seconds,
            )
        )
    if at_all:
        found.append(
            Violation(
                kind="mention_all",
                reason="@全体",
                action=policy.mention_all_action,
                recall=True,
                mute_seconds=policy.default_mute_seconds,
            )
        )

    best = pick_severity(found)
    if best is None:
        return None

    action = best.action
    strike = 0
    if action == ACTION_WARN:
        strike = state.bump_strike(group_id, user_id, now=now, window=policy.strike_window)
        if strike >= max(1, int(policy.warn_before_mute)):
            action = ACTION_MUTE

    mute_seconds = int(best.mute_seconds or policy.default_mute_seconds)
    if action == ACTION_MUTE:
        ceiling = int(policy.max_mute_seconds) if policy.max_mute_seconds else mute_seconds
        mute_seconds = max(0, min(mute_seconds, ceiling))

    state.mark_action(group_id, user_id, now=now)
    return Violation(
        kind=best.kind,
        reason=best.reason,
        action=action,
        recall=best.recall,
        mute_seconds=mute_seconds,
        rule_id=best.rule_id,
        strike=strike,
    )


def policy_from_settings(settings) -> Policy:
    """从 AppSettings 构造 Policy（插件侧调用）。"""
    return Policy(
        flood_window=settings.moderation_flood_window_seconds,
        flood_max=settings.moderation_flood_max_messages,
        flood_action=settings.moderation_flood_action,
        flood_mute_seconds=settings.moderation_flood_mute_seconds,
        duplicate_window=settings.moderation_duplicate_window_seconds,
        duplicate_max=settings.moderation_duplicate_max,
        duplicate_action=settings.moderation_duplicate_action,
        mention_all_action=settings.moderation_mention_all_action,
        sensitive_action=settings.moderation_sensitive_action,
        sensitive_skip=settings.moderation_sensitive_skip,
        sensitive_min_length=settings.moderation_sensitive_min_length,
        pattern_action=settings.moderation_sensitive_pattern_action,
        cooldown=settings.moderation_action_cooldown_seconds,
        default_mute_seconds=settings.moderation_default_mute_seconds,
        max_mute_seconds=settings.moderation_max_mute_seconds,
        warn_before_mute=settings.moderation_warn_before_mute,
        strike_window=settings.moderation_strike_window_seconds,
    )


# ---------- 规则存取（数据库） ----------


def _to_rule(row: ModerationRule) -> Rule:
    return Rule(
        id=int(row.id),
        group_id=str(row.group_id or ""),
        kind=str(row.kind or KIND_KEYWORD),
        pattern=str(row.pattern or ""),
        action=str(row.action or ACTION_WARN),
        recall=bool(row.recall),
        mute_seconds=int(row.mute_seconds or DEFAULT_MUTE_SECONDS),
        enabled=bool(row.enabled),
        note=str(row.note or ""),
    )


async def load_rules(group_id: str) -> list[Rule]:
    """载入某群可用的全部规则（全局 + 本群，叠加生效）。"""
    gid = str(group_id)
    async with db.get_session() as session:
        rows = (
            await session.execute(
                select(ModerationRule)
                .where(ModerationRule.group_id.in_([gid, ""]))
                .order_by(ModerationRule.id)
            )
        ).scalars().all()
    return [_to_rule(row) for row in rows]


async def add_rule(
    kind: str,
    pattern: str,
    action: str,
    *,
    group_id: str = "",
    recall: bool = True,
    mute_seconds: int = 0,
    note: str = "",
    created_by: str = "",
) -> int:
    """新增规则，返回新行 id。"""
    if kind not in VALID_KINDS:
        raise ValueError("未知规则类型：" + repr(kind))
    if action not in VALID_ACTIONS:
        raise ValueError("未知动作：" + repr(action))
    async with db.get_session() as session:
        row = ModerationRule(
            group_id=str(group_id),
            kind=str(kind),
            pattern=str(pattern),
            action=str(action),
            recall=1 if recall else 0,
            mute_seconds=int(mute_seconds or DEFAULT_MUTE_SECONDS),
            enabled=1,
            note=str(note),
            created_by=str(created_by),
            created_at=utc_now(),
        )
        session.add(row)
        await session.commit()
        return int(row.id)


async def delete_rule(rule_id: int, *, group_id: str | None = None) -> bool:
    """删除规则；给了 group_id 时只允许删本群或全局规则。"""
    async with db.get_session() as session:
        row = (
            await session.execute(
                select(ModerationRule).where(ModerationRule.id == int(rule_id))
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        if group_id is not None and str(row.group_id) not in (str(group_id), ""):
            return False
        await session.delete(row)
        await session.commit()
        return True


async def list_rules(
    group_id: str, *, kind: str | None = None, limit: int = 20
) -> list[Rule]:
    """本群可用规则（本群在前，含全局），最多 limit 条。"""
    rules = await load_rules(group_id)
    gid = str(group_id)
    if kind:
        rules = [rule for rule in rules if rule.kind == kind]
    rules.sort(key=lambda rule: (0 if rule.group_id == gid else 1, rule.kind, rule.id))
    return rules[: max(1, int(limit))]
