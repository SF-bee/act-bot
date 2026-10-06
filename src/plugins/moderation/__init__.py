"""moderation：群风控（敏感信息撤回警告 / 刷屏禁言 / 群管理命令）。

- 订阅 MessageReceived（feature=moderation）：规则 / 刷屏 / 复读 / @全体 → 处置；
- /mod 管理规则与状态；/warn /mute /unmute /kick /recall 手动群管理；
- **支持私聊管理**：/use 绑定默认群，或任意命令加 -g <群号> 单次指定；
- -s 静默：不在群里发通告，只写审计。

分层约定：纯逻辑在 src/core/moderation.py，目标群解析在 src/core/scope.py。
"""
from __future__ import annotations

import logging
import time

from nonebot import on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.plugin import PluginMetadata

from src.core import audit, features, moderation, persona, scope, sensitive, stats
from src.core import permissions as perms
from src.core.config import get_settings
from src.core.events import MessageReceived, subscribe
from src.core.onebot import command_prefixes, safe_group_name, safe_member_label

logger = logging.getLogger("actbot.moderation")

__plugin_meta__ = PluginMetadata(
    name="moderation",
    description="群风控：敏感信息撤回警告、刷屏禁言、群管理命令（支持私聊管理）",
    usage=(
        "/mod [-g 群号] — 查看本群风控状态\n"
        "/mod list [-g 群号] [kind] — 列出规则\n"
        "/mod add [-g 群号] [--global] [-n] <kind> | <pattern> | <action> | <秒> — 新增规则\n"
        "/mod del [-g 群号] <id> — 删除规则\n"
        "/mod test [-g 群号] <文本> — 空跑：看会命中什么（不处置）\n"
        "/mod log [-g 群号] [n] — 最近处置记录\n"
        "/warn [-g 群号] [-s] <qq> [原因] — 手动警告\n"
        "/mute [-g 群号] [-s] <qq> [秒] — 手动禁言（默认 600 秒）\n"
        "/unmute [-g 群号] [-s] <qq> — 解除禁言\n"
        "/kick [-g 群号] [-s] <qq> — 移出本群\n"
        "/recall [-g 群号] [message_id] — 撤回消息（群内可直接回复目标消息）"
    ),
    extra={"role": "admin", "order": 150},
)

mod_cmd = on_command("mod", priority=10, block=True)
warn_cmd = on_command("warn", priority=10, block=True)
mute_cmd = on_command("mute", priority=10, block=True)
unmute_cmd = on_command("unmute", priority=10, block=True)
kick_cmd = on_command("kick", priority=10, block=True)
recall_cmd = on_command("recall", priority=10, block=True)

_STATE = moderation.ModerationState()


# ---------- 小工具 ----------


def _is_group(event: MessageEvent) -> bool:
    return isinstance(event, GroupMessageEvent)


def _event_group(event: MessageEvent) -> str:
    return str(event.group_id) if isinstance(event, GroupMessageEvent) else ""


def _command_body(event: MessageEvent) -> list[str]:
    parts = event.message.extract_plain_text().split()
    return parts[1:] if parts else []


def _resolve_scope(event: MessageEvent) -> scope.ScopeResult:
    return scope.extract_scope(
        _command_body(event),
        is_group=_is_group(event),
        event_group_id=_event_group(event),
        actor_qq=str(event.user_id),
    )


def _image_ids(raw) -> list[str]:
    try:
        segments = list(getattr(raw, "message", None))
    except TypeError:
        return []
    out: list[str] = []
    for segment in segments:
        if getattr(segment, "type", "") != "image":
            continue
        data = getattr(segment, "data", {}) or {}
        file_id = str(data.get("file", "") or "")
        if file_id:
            out.append(file_id)
    return out


async def _bot_is_admin(bot: Bot, group_id: str) -> bool:
    try:
        info = await bot.get_group_member_info(
            group_id=int(group_id), user_id=int(bot.self_id), no_cache=True
        )
        return str(info.get("role", "") or "") in ("admin", "owner")
    except Exception:  # noqa: BLE001 - 拿不到就当没有
        return False


def _detail(violation: moderation.Violation, message_id: str = "", extra: str = "") -> str:
    parts = ["reason=" + violation.reason]
    if violation.rule_id:
        parts.append("rule=#" + str(violation.rule_id))
    if message_id:
        parts.append("msg=" + str(message_id))
    if extra:
        parts.append(extra)
    return " ".join(parts)


# ---------- 处置执行 ----------


async def _notify(
    bot: Bot,
    group_id: str,
    user_id: str,
    violation: moderation.Violation,
    settings,
    *,
    notice: str = "",
) -> None:
    """把警告/通告发到群里（@ 当事人）。失败只记日志。"""
    nickname = await safe_member_label(bot, group_id, user_id)
    text = notice or moderation.render_warn(
        settings.moderation_warn_text,
        nickname=nickname,
        user_id=user_id,
        reason=violation.reason,
        count=violation.strike or 1,
        limit=settings.moderation_warn_before_mute,
        bot_name=persona.name(),
        bot_title=persona.title(),
    )
    message = Message()
    if violation.action in (moderation.ACTION_WARN, moderation.ACTION_MUTE):
        message += MessageSegment.at(user_id)
        message += MessageSegment.text("\n")
    message += MessageSegment.text(text)
    try:
        await bot.send_group_msg(group_id=int(group_id), message=message)
        stats.record_auto_reply(group_id, tz_name=settings.timezone)
    except Exception:  # noqa: BLE001 - 通告失败不影响主流程
        logger.exception("发送风控通告失败：group=%s", group_id)


async def _apply(
    bot: Bot,
    group_id: str,
    user_id: str,
    violation: moderation.Violation,
    settings,
    *,
    message_id: str = "",
    actor_qq: str = "auto",
    silent: bool = False,
    notice: str = "",
) -> list[str]:
    """执行一次处置；返回人类可读的结果行（用于回复管理员）。"""
    lines: list[str] = []
    if settings.moderation_dry_run:
        await audit.record(
            "moderation." + violation.action,
            actor_qq=actor_qq,
            group_id=group_id,
            detail="dry-run " + _detail(violation, message_id),
        )
        logger.info("dry-run 风控处置：group=%s user=%s action=%s", group_id, user_id, violation.action)
        return ["（dry-run 未执行）"]

    if violation.recall and message_id:
        try:
            await bot.delete_msg(message_id=int(message_id))
            lines.append("已撤回消息")
            await audit.record(
                "moderation.recall",
                actor_qq=actor_qq,
                group_id=group_id,
                detail=_detail(violation, message_id),
            )
        except Exception:  # noqa: BLE001 - 机器人可能不是管理员 / 消息已过期
            logger.exception("撤回失败：group=%s msg=%s", group_id, message_id)
            lines.append("撤回失败（机器人可能不是管理员，或消息已过期）")

    if violation.action == moderation.ACTION_MUTE:
        try:
            await bot.set_group_ban(
                group_id=int(group_id), user_id=int(user_id), duration=int(violation.mute_seconds)
            )
            lines.append("已禁言 {0} 秒".format(violation.mute_seconds))
            await audit.record(
                "moderation.mute",
                actor_qq=actor_qq,
                group_id=group_id,
                detail=_detail(violation, message_id, "seconds={0}".format(violation.mute_seconds)),
            )
        except Exception:  # noqa: BLE001
            logger.exception("禁言失败：group=%s user=%s", group_id, user_id)
            lines.append("禁言失败（机器人可能不是管理员）")
    elif violation.action == moderation.ACTION_KICK:
        try:
            await bot.set_group_kick(group_id=int(group_id), user_id=int(user_id))
            lines.append("已移出本群")
            await audit.record(
                "moderation.kick",
                actor_qq=actor_qq,
                group_id=group_id,
                detail=_detail(violation, message_id),
            )
        except Exception:  # noqa: BLE001
            logger.exception("踢人失败：group=%s user=%s", group_id, user_id)
            lines.append("踢人失败（机器人可能不是管理员）")
    elif violation.action == moderation.ACTION_WARN:
        await audit.record(
            "moderation.warn",
            actor_qq=actor_qq,
            group_id=group_id,
            detail=_detail(violation, message_id),
        )

    if not silent and violation.action in (
        moderation.ACTION_WARN,
        moderation.ACTION_MUTE,
        moderation.ACTION_KICK,
    ):
        await _notify(bot, group_id, user_id, violation, settings, notice=notice)
        lines.append("已在群里通告")
    return lines


# ---------- 自动风控订阅 ----------


@subscribe(MessageReceived, feature=features.FEATURE_MODERATION, name="moderation")
async def _on_message(event: MessageReceived, bot: Bot) -> None:
    if not event.is_group:
        return
    settings = get_settings()
    if not settings.feature(features.FEATURE_MODERATION):
        return
    if event.user_id == str(getattr(bot, "self_id", "")):
        return
    text = event.text or ""
    if text.startswith(command_prefixes()):
        return
    if settings.moderation_exempt_group_admins and event.sender_role in ("owner", "admin"):
        return
    if await perms.is_admin(event.user_id):
        return

    rules = await moderation.load_rules(event.group_id)
    dict_hits: list[str] = []
    pinyin_hits: list[str] = []
    pattern_hits: list[tuple[str, str]] = []
    if settings.moderation_sensitive_dict:
        dict_hits = sensitive.find(
            text,
            skip=settings.moderation_sensitive_skip,
            min_length=settings.moderation_sensitive_min_length,
            traditional=settings.moderation_sensitive_traditional,
        )
        if settings.moderation_sensitive_pinyin:
            pinyin_hits = sensitive.find_pinyin(text)
    if settings.moderation_sensitive_patterns:
        pattern_hits = sensitive.find_patterns(text)
    violation = moderation.decide(
        rules=rules,
        text=text,
        image_ids=_image_ids(event.raw),
        dict_hits=dict_hits,
        pinyin_hits=pinyin_hits,
        pattern_hits=pattern_hits,
        at_all=event.at_all,
        group_id=event.group_id,
        user_id=event.user_id,
        state=_STATE,
        now=time.monotonic(),
        policy=moderation.policy_from_settings(settings),
    )
    if violation is None:
        return
    logger.info(
        "风控命中（%s）：group=%s user=%s → %s",
        violation.reason, event.group_id, event.user_id, violation.action,
    )
    await _apply(
        bot, event.group_id, event.user_id, violation, settings, message_id=event.message_id
    )


# ---------- /mod 管理 ----------


def _mod_usage() -> str:
    return (
        "用法：\n"
        "· /mod — 状态\n"
        "· /mod list [kind] — 列出规则\n"
        "· /mod add [--global] [-n] <kind> | <pattern> | <action> | <秒>\n"
        "· /mod del <id>\n"
        "· /mod test <文本> — 空跑\n"
        "· /mod log [n] — 处置记录\n"
        "kind：keyword｜regex；action：warn｜recall_only｜mute｜kick"
    )


async def _render_status(bot: Bot, group_id: str) -> str:
    settings = get_settings()
    rules = await moderation.load_rules(group_id)
    group_on = await _feature_on(group_id)
    has_admin = await _bot_is_admin(bot, group_id)
    lines = [
        "群风控状态（群 {0}）".format(group_id),
        "· 本群开关：{0}｜全局：{1}".format(
            "已开启" if group_on else "已关闭",
            "已开启" if settings.feature(features.FEATURE_MODERATION) else "已关闭",
        ),
        "· 可用规则 {0} 条".format(len(rules)),
        "· 内置敏感词库：{0}".format(
            "已加载 {0} 词".format(sensitive.word_count())
            if settings.moderation_sensitive_dict
            else "已关闭"
        ),
        "· 变体识别：干扰字符 {0}｜繁简 {1}｜拼音 {2}｜URL/号码 {3}".format(
            "开" if settings.moderation_sensitive_skip else "关",
            "开" if settings.moderation_sensitive_traditional else "关",
            "开" if settings.moderation_sensitive_pinyin else "关",
            "开" if settings.moderation_sensitive_patterns else "关",
        ),
        "· 阈值：刷屏 {0} 条/{1:g}s｜复读 {2} 次/{3:g}s｜警告 {4} 次转禁言".format(
            settings.moderation_flood_max_messages,
            settings.moderation_flood_window_seconds,
            settings.moderation_duplicate_max,
            settings.moderation_duplicate_window_seconds,
            settings.moderation_warn_before_mute,
        ),
        "· 默认禁言 {0} 秒｜上限 {1} 秒｜dry-run：{2}".format(
            settings.moderation_default_mute_seconds,
            settings.moderation_max_mute_seconds,
            "开" if settings.moderation_dry_run else "关",
        ),
        "· 机器人群管理权限：{0}".format("有" if has_admin else "没有（撤回/禁言会失败，请给机器人管理员）"),
    ]
    return "\n".join(lines)


async def _feature_on(group_id: str) -> bool:
    from src.core import groups

    return await groups.feature_enabled(
        group_id,
        features.FEATURE_MODERATION,
        default=features.default_of(features.FEATURE_MODERATION),
    )


@mod_cmd.handle()
async def _handle_mod(bot: Bot, event: MessageEvent) -> None:
    if not await perms.is_admin(str(event.user_id)):
        await mod_cmd.finish()
    resolved = _resolve_scope(event)
    if resolved.error:
        await mod_cmd.finish(resolved.error)
    action, args = moderation.parse_mod_command(resolved.tokens)
    if action == "unknown":
        await mod_cmd.finish(_mod_usage())
    group_id = resolved.group_id
    settings = get_settings()

    if action == "":
        await mod_cmd.finish(await _render_status(bot, group_id))

    if action == "add":
        global_scope = False
        clean: list[str] = []
        for token in args:
            if token == "--global":
                global_scope = True
            else:
                clean.append(token)
        parsed = moderation.parse_add_args(clean)
        if not parsed.ok:
            await mod_cmd.finish(_mod_usage())
        target = "" if global_scope else group_id
        rule_id = await moderation.add_rule(
            parsed.kind,
            parsed.pattern,
            parsed.action,
            group_id=target,
            recall=parsed.recall,
            mute_seconds=parsed.mute_seconds,
            created_by=str(event.user_id),
        )
        await audit.record(
            "moderation.rule.add",
            actor_qq=str(event.user_id),
            group_id=group_id,
            detail="#{0} {1} {2}".format(rule_id, parsed.kind, parsed.action),
        )
        await mod_cmd.finish(
            "已新增规则 #{0}（{1}｜{2}｜{3}｜{4}）：{5}".format(
                rule_id,
                "全局" if global_scope else "本群",
                parsed.kind,
                parsed.action,
                "撤回" if parsed.recall else "不撤回",
                parsed.pattern,
            )
        )

    if action == "del":
        if not args or not args[0].lstrip("#").isdigit():
            await mod_cmd.finish("用法：/mod del <id>（id 见 /mod list）")
        rule_id = int(args[0].lstrip("#"))
        if not await moderation.delete_rule(rule_id, group_id=group_id):
            await mod_cmd.finish("没有这条规则，或它属于别的群：#" + str(rule_id))
        await audit.record(
            "moderation.rule.del",
            actor_qq=str(event.user_id),
            group_id=group_id,
            detail="#" + str(rule_id),
        )
        await mod_cmd.finish("已删除规则 #{0}".format(rule_id))

    if action == "test":
        text = " ".join(args)
        rules = await moderation.load_rules(group_id)
        hits = moderation.match_rules(rules, text)
        dict_hits: list[str] = []
        pinyin_hits: list[str] = []
        pattern_hits: list[tuple[str, str]] = []
        if settings.moderation_sensitive_dict:
            dict_hits = sensitive.find(
                text,
                skip=settings.moderation_sensitive_skip,
                min_length=settings.moderation_sensitive_min_length,
                traditional=settings.moderation_sensitive_traditional,
            )
            if settings.moderation_sensitive_pinyin:
                pinyin_hits = sensitive.find_pinyin(text)
        if settings.moderation_sensitive_patterns:
            pattern_hits = sensitive.find_patterns(text)
        if not hits and not dict_hits and not pinyin_hits and not pattern_hits:
            await mod_cmd.finish("没有命中任何规则。")
        lines = ["命中 {0} 条规则（空跑，不处置）：".format(len(hits))]
        for rule in hits:
            lines.append(
                "· #{0} {1}/{2} → {3}{4}".format(
                    rule.id,
                    "全局" if rule.group_id == "" else "本群",
                    rule.kind,
                    rule.action,
                    "" if rule.recall else "（不撤回）",
                )
            )
        if dict_hits:
            lines.append("· 内置敏感词库命中 {0} 个：{1}".format(len(dict_hits), "、".join(dict_hits[:5])))
        if pinyin_hits:
            lines.append("· 拼音变体命中 {0} 个：{1}".format(len(pinyin_hits), "、".join(pinyin_hits[:5])))
        if pattern_hits:
            lines.append(
                "· 内置正则命中：{0}".format(
                    "、".join(moderation.PATTERN_LABELS.get(k, k) + "=" + v for k, v in pattern_hits[:5])
                )
            )
        await mod_cmd.finish("\n".join(lines))

    if action == "list":
        kind = args[0].strip().lower() if args else ""
        rules = await moderation.list_rules(group_id, limit=20)
        if kind:
            rules = [rule for rule in rules if rule.kind == kind]
        if not rules:
            await mod_cmd.finish("（没有匹配的规则）\n" + _mod_usage())
        lines = ["风控规则（本群优先，最多 20 条）："]
        for rule in rules:
            scope_tag = "[全局]" if rule.group_id == "" else "[本群]"
            lines.append(
                "· #{0} {1} {2}/{3} → {4}{5}".format(
                    rule.id,
                    scope_tag,
                    rule.kind,
                    rule.action,
                    rule.pattern[:30],
                    "" if rule.recall else "（不撤回）",
                )
            )
        lines.append("删除：/mod del <id>")
        await mod_cmd.finish("\n".join(lines))

    if action == "log":
        limit = audit.DEFAULT_LIMIT
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                await mod_cmd.finish("用法：/mod log [条数]（1-50，默认 10）")
        rows = await audit.recent(limit=limit, group_id=group_id)
        rows = [row for row in rows if str(row.action).startswith("moderation.")]
        if not rows:
            await mod_cmd.finish("暂无风控处置记录。")
        tz_name = settings.timezone
        lines = ["最近 {0} 条风控记录：".format(len(rows))]
        lines.extend("· " + audit.format_record(row, tz_name=tz_name) for row in rows)
        await mod_cmd.finish("\n".join(lines))


# ---------- 手动群管理 ----------


def _parse_target(args: list[str], *, need_seconds: bool = False) -> tuple[str, int]:
    """返回 (qq, seconds)；非法返回 ("", 0)。"""
    if not args or not args[0].isdigit():
        return "", 0
    seconds = 0
    if need_seconds and len(args) > 1:
        if not args[1].isdigit():
            return "", 0
        seconds = int(args[1])
    return args[0], seconds


@warn_cmd.handle()
async def _handle_warn(bot: Bot, event: MessageEvent) -> None:
    if not await perms.is_admin(str(event.user_id)):
        await warn_cmd.finish()
    resolved = _resolve_scope(event)
    if resolved.error:
        await warn_cmd.finish(resolved.error)
    target, _ = _parse_target(resolved.tokens)
    if not target:
        await warn_cmd.finish("用法：/warn [-g 群号] [-s] <qq> [原因]")
    settings = get_settings()
    reason = " ".join(resolved.tokens[1:]).strip() or "管理员警告"
    strike = _STATE.bump_strike(
        resolved.group_id, target, now=time.monotonic(), window=settings.moderation_strike_window_seconds
    )
    action = moderation.ACTION_WARN
    if strike >= max(1, settings.moderation_warn_before_mute):
        action = moderation.ACTION_MUTE
    violation = moderation.Violation(
        kind="manual",
        reason=reason,
        action=action,
        recall=False,
        mute_seconds=settings.moderation_default_mute_seconds,
        strike=strike,
    )
    lines = await _apply(
        bot,
        resolved.group_id,
        target,
        violation,
        settings,
        actor_qq=str(event.user_id),
        silent=resolved.silent,
    )
    await warn_cmd.finish("已警告 {0}（第 {1} 次）{2}".format(target, strike, "；" + "；".join(lines) if lines else ""))


@mute_cmd.handle()
async def _handle_mute(bot: Bot, event: MessageEvent) -> None:
    if not await perms.is_admin(str(event.user_id)):
        await mute_cmd.finish()
    resolved = _resolve_scope(event)
    if resolved.error:
        await mute_cmd.finish(resolved.error)
    target, seconds = _parse_target(resolved.tokens, need_seconds=True)
    if not target:
        await mute_cmd.finish("用法：/mute [-g 群号] [-s] <qq> [秒]")
    settings = get_settings()
    seconds = seconds or settings.moderation_default_mute_seconds
    ceiling = settings.moderation_max_mute_seconds or seconds
    seconds = max(0, min(seconds, ceiling))
    violation = moderation.Violation(
        kind="manual",
        reason="管理员禁言",
        action=moderation.ACTION_MUTE,
        recall=False,
        mute_seconds=seconds,
    )
    lines = await _apply(
        bot, resolved.group_id, target, violation, settings,
        actor_qq=str(event.user_id), silent=resolved.silent,
        notice="管理员已禁言该成员 {0} 秒".format(seconds),
    )
    await mute_cmd.finish("已处理 {0}：{1}".format(target, "；".join(lines) or "完成"))


@unmute_cmd.handle()
async def _handle_unmute(bot: Bot, event: MessageEvent) -> None:
    if not await perms.is_admin(str(event.user_id)):
        await unmute_cmd.finish()
    resolved = _resolve_scope(event)
    if resolved.error:
        await unmute_cmd.finish(resolved.error)
    target, _ = _parse_target(resolved.tokens)
    if not target:
        await unmute_cmd.finish("用法：/unmute [-g 群号] [-s] <qq>")
    try:
        await bot.set_group_ban(group_id=int(resolved.group_id), user_id=int(target), duration=0)
    except Exception:  # noqa: BLE001
        logger.exception("解除禁言失败：group=%s user=%s", resolved.group_id, target)
        await unmute_cmd.finish("解除禁言失败（机器人可能不是管理员）")
    await audit.record(
        "moderation.unmute", actor_qq=str(event.user_id), group_id=resolved.group_id, detail="user=" + target
    )
    await unmute_cmd.finish("已解除 {0} 的禁言".format(target))


@kick_cmd.handle()
async def _handle_kick(bot: Bot, event: MessageEvent) -> None:
    if not await perms.is_admin(str(event.user_id)):
        await kick_cmd.finish()
    resolved = _resolve_scope(event)
    if resolved.error:
        await kick_cmd.finish(resolved.error)
    target, _ = _parse_target(resolved.tokens)
    if not target:
        await kick_cmd.finish("用法：/kick [-g 群号] [-s] <qq>")
    settings = get_settings()
    violation = moderation.Violation(
        kind="manual", reason="管理员移出", action=moderation.ACTION_KICK, recall=False
    )
    lines = await _apply(
        bot, resolved.group_id, target, violation, settings,
        actor_qq=str(event.user_id), silent=resolved.silent,
        notice="管理员已将成员移出本群",
    )
    await kick_cmd.finish("已处理 {0}：{1}".format(target, "；".join(lines) or "完成"))


@recall_cmd.handle()
async def _handle_recall(bot: Bot, event: MessageEvent) -> None:
    if not await perms.is_admin(str(event.user_id)):
        await recall_cmd.finish()
    resolved = _resolve_scope(event)
    if resolved.error:
        await recall_cmd.finish(resolved.error)
    message_id = ""
    if isinstance(event, GroupMessageEvent) and getattr(event, "reply", None) is not None:
        message_id = str(event.reply.message_id)
    elif resolved.tokens and resolved.tokens[0].isdigit():
        message_id = resolved.tokens[0]
    if not message_id:
        await recall_cmd.finish("用法：/recall [-g 群号] [message_id]（群内可直接回复目标消息）")
    try:
        await bot.delete_msg(message_id=int(message_id))
    except Exception:  # noqa: BLE001
        logger.exception("撤回失败：group=%s msg=%s", resolved.group_id, message_id)
        await recall_cmd.finish("撤回失败（机器人可能不是管理员，或消息已过期）")
    await audit.record(
        "moderation.recall",
        actor_qq=str(event.user_id),
        group_id=resolved.group_id,
        detail="msg=" + message_id + " manual",
    )
    await recall_cmd.finish("已撤回消息 {0}".format(message_id))
