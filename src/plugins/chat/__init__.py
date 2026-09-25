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

from src.core import audit, chat, features, groups
from src.core import permissions as perms
from src.core.config import get_settings
from src.core.events import MessageReceived, subscribe
from src.core.onebot import safe_group_name, safe_member_label

logger = logging.getLogger("actbot.chat")

__plugin_meta__ = PluginMetadata(
    name="chat",
    description="聊天引擎（@ 或关键词唤醒；确定性机制，不接 LLM）",
    usage=(
        "/chat — 查看聊天互动状态与规则统计\n"
        "/chat list [kind] — 列出规则（含 id）\n"
        "/chat add [-g] <kind> <触发词> <回复> — 新增规则（-g 为全局默认）\n"
        "/chat del <id> — 删除规则"
    ),
    extra={"role": "admin", "order": 130},
)

chat_cmd = on_command("chat", priority=10, block=True)

_STATE = chat.ChatState()


def _command_prefixes() -> tuple[str, ...]:
    """从 nonebot 配置读命令前缀，避免把命令当聊天内容回应。"""
    try:
        from nonebot import get_driver

        starts = tuple(get_driver().config.command_start)
        return starts or ("/",)
    except Exception:  # noqa: BLE001 - 取不到就用默认前缀
        return ("/",)


@subscribe(MessageReceived, feature=features.FEATURE_CHAT, name="chat")
async def _on_message(event: MessageReceived, bot: Bot) -> None:
    """群消息 → 判断是否在叫它 → 决定是否回应。"""
    if not event.is_group:
        return
    text = (event.text or "").strip()
    if not text and not event.at_self:
        return
    if text.startswith(_command_prefixes()):
        return  # 命令交给命令系统，聊天引擎不掺和

    settings = get_settings()
    rules = await chat.load_rules(event.group_id)
    decision = chat.decide(
        rules,
        text=text,
        at_self=event.at_self,
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
        log = logger.info if event.at_self else logger.debug
        log(
            "不回应（%s）：group=%s user=%s at_self=%s text=%r",
            decision.reason, event.group_id, event.user_id, event.at_self, text[:30],
        )
        return

    reply = chat.render_reply(
        decision.reply,
        user_id=event.user_id,
        nickname=await safe_member_label(bot, event.group_id, event.user_id),
        group_name=await safe_group_name(bot, event.group_id),
    )
    try:
        await bot.send_group_msg(group_id=int(event.group_id), message=reply)
    except Exception:  # noqa: BLE001 - 发送失败只记日志，不影响其它事件
        logger.exception("聊天回应发送失败：group=%s user=%s", event.group_id, event.user_id)
        return
    logger.info(
        "聊天回应（%s）：group=%s user=%s → %s",
        decision.reason, event.group_id, event.user_id, reply[:40],
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
        await chat_cmd.finish("聊天命令要在群里用。")

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
            await chat_cmd.finish("用法：/chat del <id>（id 见 /chat list）")
        rule_id = int(args[0].lstrip("#"))
        if not await chat.delete_rule(rule_id, group_id=group_id):
            await chat_cmd.finish("没有这条规则，或它属于别的群：#{0}".format(rule_id))
        await audit.record(
            "chat.del", actor_qq=str(event.user_id), group_id=group_id, detail="#{0}".format(rule_id)
        )
        await chat_cmd.finish("已删除规则 #{0}".format(rule_id))

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
        "聊天互动（本群）：{0}｜全局：{1}".format(
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

