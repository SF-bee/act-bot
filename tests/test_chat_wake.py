"""插件层测试：chat 的 @/称呼唤醒接线（导入插件需要先初始化 nonebot）。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core import chat, config, events
from src.core.events import MessageReceived


@pytest.fixture(scope="module")
def chat_plugin():
    """导入 src.plugins.chat（导入即注册订阅者）；用完还原订阅表，避免污染别的测试。"""
    snapshot = list(events._subscriptions)
    import nonebot

    nonebot.init()
    from src.plugins import chat as plugin

    yield plugin
    events.clear_subscriptions()
    events._subscriptions.extend(snapshot)


@pytest.fixture()
def settings(tmp_path):
    return config.load_settings(
        env={}, toml_path=tmp_path / "missing.toml", load_dotenv_first=False
    )


def test_plugin_wake_reason_delegates_to_core(chat_plugin, settings):
    assert settings.persona_aliases[0] == "Yulia"
    assert chat_plugin._wake_reason(SimpleNamespace(at_self=True, text=""), settings) == "at"
    # 协议端把 @ 降级成纯文本时的兜底
    assert chat_plugin._wake_reason(SimpleNamespace(at_self=False, text="@Yulia 在吗"), settings) == "name"
    assert chat_plugin._wake_reason(SimpleNamespace(at_self=False, text="今天天气不错"), settings) == ""
    # 线上真实形态：at 段缺失，只靠 raw_message 里的 CQ 码认出来
    assert chat_plugin._wake_reason(
        SimpleNamespace(
            at_self=False,
            text="",
            raw=SimpleNamespace(self_id="446619493", raw_message="[CQ:at,qq=446619493,name=Yulia] "),
        ),
        settings,
    ) == "at_raw"


def test_plugin_at_qqs_and_mention_diagnostic(chat_plugin):
    segments = [
        SimpleNamespace(type="at", data={"qq": "446619493"}),
        SimpleNamespace(type="text", data={"text": " 在吗"}),
    ]
    raw = SimpleNamespace(
        self_id="446619493",
        raw_message="[CQ:at,qq=446619493,name=Yulia ] 在吗",
        message=segments,
    )
    event = SimpleNamespace(raw=raw)
    assert chat_plugin._at_qqs(event) == ["446619493"]
    assert chat_plugin._mention_diagnostic(event) != ""
    assert chat_plugin._at_qqs(SimpleNamespace(raw=None)) == []


def test_plugin_group_diagnostic(chat_plugin):
    assert chat_plugin._group_diagnostic(SimpleNamespace(raw=None)) == ""
    assert chat_plugin._group_diagnostic(
        SimpleNamespace(raw=SimpleNamespace(message_type="private"))
    ) == ""
    assert chat_plugin._group_diagnostic(
        SimpleNamespace(raw=SimpleNamespace(message_type="group", group_id=123))
    ) != ""
    assert chat_plugin._group_diagnostic(
        SimpleNamespace(raw=SimpleNamespace(message_type="", group_id=123))
    ) != ""


async def test_on_message_logs_when_group_message_looks_private(chat_plugin, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="actbot.chat"):
        await chat_plugin._on_message(
            MessageReceived(
                group_id="999",
                user_id="101",
                text=" ",
                is_group=False,
                raw=SimpleNamespace(message_type="group", group_id=999),
            ),
            SimpleNamespace(),
        )
    assert "群消息被当成非群消息" in caplog.text


async def test_on_message_logs_never_contain_body(chat_plugin, caplog):
    """日志只留长度与指纹：正文（哪怕截断）不能进 systemd / docker 日志。"""
    import logging

    sentinel = "秘密正文哨兵不要在日志里出现"
    with caplog.at_level(logging.WARNING, logger="actbot.chat"):
        await chat_plugin._on_message(
            MessageReceived(
                group_id="999",
                user_id="101",
                text=sentinel,
                is_group=False,
                raw=SimpleNamespace(message_type="group", group_id=999),
            ),
            SimpleNamespace(),
        )
    assert sentinel not in caplog.text, "日志里不能出现消息正文"
    assert "fp=" in caplog.text and "text_shape=" in caplog.text


async def test_on_message_treats_plain_text_call_as_mention(chat_plugin, monkeypatch):
    seen: dict[str, object] = {}

    async def fake_load_rules(group_id):
        return []

    def fake_decide(rules, *, text, at_self, **kwargs):
        seen["at_self"] = at_self
        seen["text"] = text
        return chat.Decision(reply=None, reason="no_match")

    monkeypatch.setattr(chat_plugin.chat, "load_rules", fake_load_rules)
    monkeypatch.setattr(chat_plugin.chat, "decide", fake_decide)

    event = MessageReceived(group_id="999", user_id="101", text="@Yulia 在吗", at_self=False)
    await chat_plugin._on_message(event, SimpleNamespace())
    assert seen["at_self"] is True and seen["text"] == "@Yulia 在吗"

    seen.clear()
    await chat_plugin._on_message(
        MessageReceived(group_id="999", user_id="102", text="今天天气不错", at_self=False),
        SimpleNamespace(),
    )
    assert seen["at_self"] is False
