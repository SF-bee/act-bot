"""chat：聊天引擎（确定性机制，不接 LLM）。

唤醒方式两种：**@ 机器人** 或 **消息命中关键词/正则规则**。
- 被 @ 必回，且会分档升级：mention → mention_more → mention_tired（连续被叫）
- 关键词按 `[chat].reply_probability` 概率回
- 同一人同群 `[chat].cooldown_seconds` 内不打扰
- 群级开关走 `/config chat on|off`（本插件不提供开关命令，遵守命令分层约定）

管理员命令：
- `/chat` — 查看状态与规则统计
- `/chat list [kind]` — 列出规则（含 id）
- `/chat add [-g] <kind> <触发词> <回复>` — 新增规则（-g 为全局默认）
- `/chat del <id>` — 删除规则
"""
from __future__ import annotations

import logging
import time
from collections import Counter

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.plugin import PluginMetadata

from src.core import audit, chat, features, groups, logsafe, stats
from src.core import permissions as perms
from src.core.config import AppSettings, get_settings
from src.core.events import MessageReceived, subscribe
from src.core.onebot import command_prefixes, safe_group_name, safe_member_label

logger = logging.getLogger("actbot.chat")

__plugin_meta__ = PluginMetadata(
    name="chat",
    description="聊天引擎（@ 或关键词唤醒；确定性机制，不接 LLM）",
    usage=(
        "/chat — 查看聊天互动状态与规则统计（开关：/config chat on|off）\n"
        "/chat list [kind] — 列出规则（含 id）\n"
        "/chat add [-g] <kind> <触发词> <回复> — 新增规则（-g 为全局默认）\n"
        "/chat del <id> — 删除规则"
    ),
    extra={"role": "admin", "order": 130},
)

chat_cmd = on_command("chat", priority=10, block=True)

_STATE = chat.ChatState()


def _raw_field(event: MessageReceived, key: str) -> str:
    """取底层事件的字符串字段（取不到返回空串）。"""
    return str(getattr(getattr(event, "raw", None), key, "") or "")


def _wake_reason(event: MessageReceived, settings: AppSettings) -> str:
    """这条群消息是不是在叫机器人：返回 "at"、"at_raw"、"name" 或空串（判定见 core.chat）。"""
    return chat.wake_reason(
        at_self=event.at_self,
        text=event.text or "",
        aliases=settings.persona_aliases,
        self_id=_raw_field(event, "self_id"),
        raw_message=_raw_field(event, "raw_message"),
    )


def _at_qqs(event: MessageReceived) -> list[str]:
    """取原始消息里 at 段的 qq 列表（诊断用，取不到就返回空列表）。"""
    raw = getattr(event, "raw", None)
    segments = getattr(raw, "message", None)
    if not segments:
        return []
    found: list[str] = []
    for segment in segments:
        if getattr(segment, "type", "") != "at":
            continue
        data = getattr(segment, "data", None) or {}
        found.append(str(data.get("qq", "")))
    return found


def _mention_diagnostic(event: MessageReceived) -> str:
    """被 @ 却未被识别时返回一行诊断说明，否则返回空串（判定见 core.chat）。"""
    raw = getattr(event, "raw", None)
    return chat.mention_mismatch_hint(
        self_id=str(getattr(raw, "self_id", "") or ""),
        raw_message=str(getattr(raw, "raw_message", "") or ""),
        at_qqs=_at_qqs(event),
    )


def _group_diagnostic(event: MessageReceived) -> str:
    """领域事件说是私聊、底层事件却带群信息时返回诊断说明，否则返回空串。"""
    raw = getattr(event, "raw", None)
    if raw is None:
        return ""
    if str(getattr(raw, "message_type", "") or "") == "group" or getattr(raw, "group_id", None):
        return "底层事件带群信息，但 is_group=False"
    return ""


@subscribe(MessageReceived, feature=features.FEATURE_CHAT, name="chat")
async def _on_message(event: MessageReceived, bot: Bot) -> None:
    """群消息 → 判断是否在叫它 → 决定是否回应。"""
    if not event.is_group:
        # 群消息被当成私聊时在这里静默丢掉，留一条 WARNING 方便定案
        hint = _group_diagnostic(event)
        if hint:
            body = (event.text or "").strip()
            logger.warning(
                "群消息被当成非群消息：%s · group=%s user=%s raw_type=%s text_shape=%s fp=%s",
                hint, event.group_id, event.user_id,
                getattr(getattr(event, "raw", None), "message_type", ""),
                logsafe.shape(body), logsafe.fingerprint(body),
            )
        return
    text = (event.text or "").strip()
    settings = get_settings()
    called = _wake_reason(event, settings)
    if called == "at_raw":
        # 协议端没给 at 段、只给了 raw_message 里的 CQ 码：记下 payload 形态备查
        logger.info(
            "按 raw_message 识别 @（at 段缺失）：group=%s user=%s message_shape=%s raw_shape=%s fp=%s",
            event.group_id, event.user_id,
            logsafe.shape(_raw_field(event, "message")),
            logsafe.shape(_raw_field(event, "raw_message")),
            logsafe.fingerprint(text),
        )
    if not called:
        # 明明 @ 了却识别不出来：留一条 WARNING，方便下次线上复现时抓到真实 payload
        hint = _mention_diagnostic(event)
        if hint:
            logger.warning(
                "疑似被叫但未识别：%s · group=%s user=%s at_self=%s at=%s text_shape=%s fp=%s",
                hint, event.group_id, event.user_id, event.at_self, _at_qqs(event),
                logsafe.shape(text), logsafe.fingerprint(text),
            )
    if not text and not called:
        return
    if text.startswith(command_prefixes()):
        return  # 命令交给命令系统，聊天引擎不掺和

    rules = await chat.load_rules(event.group_id)
    decision = chat.decide(
        rules,
        text=text,
        at_self=bool(called),
        group_id=event.group_id,
        user_id=event.user_id,
        state=_STATE,
        now=time.monotonic(),
        cooldown=settings.chat_cooldown_seconds,
        probability=settings.chat_reply_probability,
        escalate_after=settings.chat_escalate_after,
        escalate_window=settings.chat_escalate_window_seconds,
    )
    if not decision.reply:
        # 被叫却不回应属于值得留痕的情况（排查"为什么没理我"），其余降为 debug
        log = logger.info if called else logger.debug
        log(
            "不回应（%s）：group=%s user=%s 唤醒=%s at_self=%s text_shape=%s fp=%s",
            decision.reason, event.group_id, event.user_id, called or "keyword",
            event.at_self, logsafe.shape(text), logsafe.fingerprint(text),
        )
        return

    reply = chat.render_reply(
        decision.reply,
        user_id=event.user_id,
        nickname=await safe_member_label(bot, event.group_id, event.user_id),
        group_name=await safe_group_name(bot, event.group_id),
    )
    # 发送失败不在这里吞掉：让中枢记 failed 并计入统计 errors（events.dispatch）
    await bot.send_group_msg(group_id=int(event.group_id), message=reply)
    stats.record_auto_reply(event.group_id, tz_name=settings.timezone)
    logger.info(
        "聊天回应（%s）：group=%s user=%s 唤醒=%s → reply_len=%d",
        decision.reason, event.group_id, event.user_id, called or "keyword", len(reply),
    )


def _usage_text() -> str:
    return (
        "用法：\n"
        "· /chat — 状态与规则统计\n"
        "· /chat list [kind] — 列出规则\n"
        "· /chat add [-g] <kind> <触发词> <回复> — 新增（-g 全局）\n"
        "· /chat del <id> — 删除\n"
        "kind：" + "｜".join(chat.VALID_KINDS)
    )


@chat_cmd.handle()
async def _handle_chat(bot: Bot, event: MessageEvent) -> None:
    if not await perms.is_admin(str(event.user_id)):
        await chat_cmd.finish()  # 非管理员：静默
    if not isinstance(event, GroupMessageEvent):
        await chat_cmd.finish("聊天命令要在群里管理才行哦～")

    action, args = chat.parse_chat_command(event.message.extract_plain_text())
    group_id = str(event.group_id)
    settings = get_settings()

    if action == "unknown":
        await chat_cmd.finish(_usage_text())

    if action == "add":
        scope, kind, pattern, reply = chat.parse_add_args(args)
        needs_pattern = kind in (chat.KIND_KEYWORD, chat.KIND_REGEX)
        if not kind or not reply or (needs_pattern and not pattern):
            await chat_cmd.finish(_usage_text())
        target = "" if scope == "global" else group_id
        rule_id = await chat.add_rule(
            kind, pattern, reply, group_id=target, created_by=str(event.user_id)
        )
        await audit.record(
            "chat.add",
            actor_qq=str(event.user_id),
            group_id=group_id,
            detail="#{0} {1} {2}".format(rule_id, kind, pattern or "-"),
        )
        scope_text = "全局默认" if scope == "global" else "本群"
        await chat_cmd.finish("已新增规则 #{0}（{1}｜{2}）：{3}".format(rule_id, scope_text, kind, reply))

    if action == "del":
        if not args or not args[0].lstrip("#").isdigit():
            await chat_cmd.finish("用法：/chat del <id>（id 可以在 /chat list 里找到～）")
        rule_id = int(args[0].lstrip("#"))
        if not await chat.delete_rule(rule_id, group_id=group_id):
            await chat_cmd.finish("找不到这条规则，或它属于别的群：#{0}".format(rule_id))
        await audit.record(
            "chat.del", actor_qq=str(event.user_id), group_id=group_id, detail="#{0}".format(rule_id)
        )
        await chat_cmd.finish("规则 #{0} 已删除，聊天池清爽啦～".format(rule_id))

    if action == "list":
        wanted = args[0].strip().lower() if args else ""
        rules = await chat.list_rules(group_id, limit=20)
        if wanted:
            rules = [rule for rule in rules if rule.kind == wanted]
        if not rules:
            await chat_cmd.finish("（没有匹配的规则）\n" + _usage_text())
        lines = ["规则（本群优先，最多 20 条）："]
        for rule in rules:
            scope_tag = "[全局]" if rule.group_id == "" else "[本群]"
            head = "{0} → ".format(rule.pattern) if rule.pattern else ""
            body = rule.reply if len(rule.reply) <= 24 else rule.reply[:24] + "…"
            lines.append("· #{0} {1} {2}：{3}{4}".format(rule.id, scope_tag, rule.kind, head, body))
        lines.append("删除：/chat del <id>")
        await chat_cmd.finish("\n".join(lines))

    # 默认：状态
    group_on = await groups.feature_enabled(
        group_id, features.FEATURE_CHAT, default=features.default_of(features.FEATURE_CHAT)
    )
    global_on = settings.feature(features.FEATURE_CHAT)
    rules = await chat.load_rules(group_id)
    counts = Counter(rule.kind for rule in rules if rule.enabled)
    lines = [
        "聊天互动（本群）：{0}｜全局：{1} ✨".format(
            "已开启" if group_on else "已关闭", "已开启" if global_on else "已关闭"
        ),
        "可用规则 {0} 条：{1}".format(
            sum(counts.values()),
            "、".join("{0}={1}".format(kind, counts.get(kind, 0)) for kind in chat.VALID_KINDS),
        ),
        "回应概率 {0:.0%}｜冷却 {1:g}s｜连续被叫 {2} 次进入「被叫烦了」".format(
            settings.chat_reply_probability,
            settings.chat_cooldown_seconds,
            settings.chat_escalate_after,
        ),
        "唤醒方式：@ 我，或消息里含关键词",
        "开关：/config chat on|off｜" + _usage_text().splitlines()[0].replace("用法：", ""),
    ]
    await chat_cmd.finish("\n".join(lines))
