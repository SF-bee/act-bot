"""定时推送测试：配置解析、占位符、发送目标、功能过滤与 job 注册。"""
from __future__ import annotations

from datetime import datetime

import pytest

from src.core import config, push
from src.core.config import ConfigError


class FakeBot:
    def __init__(self):
        self.self_id = "10001"
        self.private: list[tuple[str, str]] = []
        self.groups: list[tuple[str, str]] = []

    async def send_private_msg(self, *, user_id, message, **kwargs):
        self.private.append((str(user_id), str(message)))

    async def send_group_msg(self, *, group_id, message, **kwargs):
        self.groups.append((str(group_id), str(message)))


def _load(tmp_path, body: str) -> config.AppSettings:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return config.load_settings({}, path, load_dotenv_first=False)


def test_parse_push_minimal(tmp_path):
    settings = _load(
        tmp_path,
        '''
[[push]]
name = "早安"
at = "08:00"
text = "早上好"
''',
    )
    assert len(settings.pushes) == 1
    item = settings.pushes[0]
    assert (item.name, item.text) == ("早安", "早上好")
    assert item.times == ((8, 0),)
    assert item.weekdays == ()
    assert item.targets == ("admins",)
    assert item.feature == ""
    assert item.enabled is True


def test_parse_push_full(tmp_path):
    settings = _load(
        tmp_path,
        '''
[[push]]
name = "值班"
at = ["20:00", "08:00"]
weekdays = ["mon", "周五", "周一"]
targets = ["all", "123456", "all"]
text = "hi"
feature = "stats"
enabled = false
''',
    )
    item = settings.pushes[0]
    assert item.times == ((8, 0), (20, 0))
    assert item.weekdays == (0, 4)
    assert item.targets == ("all", "123456")
    assert item.feature == "stats"
    assert item.enabled is False


def test_no_push_section_is_empty(tmp_path):
    assert _load(tmp_path, '[features]\nstats = true\n').pushes == ()


@pytest.mark.parametrize(
    "body",
    [
        '[[push]]\nname="a"\nat="25:00"\ntext="x"\n',
        '[[push]]\nname="a"\nat="8:0"\ntext="x"\n',
        '[[push]]\nname="a"\ntext="x"\n',
        '[[push]]\nname="a"\nat="08:00"\ntext="x"\nweekdays=["funday"]\n',
        '[[push]]\nname="a"\nat="08:00"\ntext="x"\nfeature="nope"\n',
        '[[push]]\nname="a"\nat="08:00"\ntext="x"\ntargets=[]\n',
        '[[push]]\nname="a"\nat="08:00"\n',
        '[[push]]\nname=""\nat="08:00"\ntext="x"\n',
        '[[push]]\nname="a"\nat="08:00"\ntext="x"\nenabled="yes"\n',
        '[[push]]\nname="a"\nat="08:00"\ntext="x"\n[[push]]\nname="a"\nat="09:00"\ntext="y"\n',
    ],
)
def test_parse_push_rejects_bad_config(tmp_path, body):
    with pytest.raises(ConfigError):
        _load(tmp_path, body)


def test_render_text_placeholders():
    now = datetime(2026, 10, 7, 8, 5)
    text = push.render_text(
        "{bot_name}|{bot_title}|{date}|{time}|{weekday}",
        now=now,
        bot_name="Yulia",
        bot_title="助理",
    )
    assert text == f"Yulia|助理|2026-10-07|08:05|{config.WEEKDAY_NAMES[now.weekday()]}"
    # 未识别的花括号原样保留，不因为正文里有 { 就报错
    assert push.render_text("保留 {unknown} 与 {", now=now) == "保留 {unknown} 与 {"


async def test_send_push_to_admins(fresh_db):
    from src.core import permissions as perms

    await perms.add_admin("123456789")
    bot = FakeBot()
    schedule = config.PushSchedule(name="早", text="hello {bot_name}", targets=("admins",))
    sent = await push.send_push(schedule, bots=[bot])
    assert sent == 1
    assert bot.private[0][0] == "123456789"
    assert "Yulia" in bot.private[0][1]


async def test_send_push_to_all_groups_respects_feature(fresh_db):
    from src.core import groups

    await groups.upsert_group("100", "一群")
    await groups.upsert_group("200", "二群")
    await groups.set_feature("200", "chat", False)
    bot = FakeBot()
    schedule = config.PushSchedule(name="群发", text="公告", targets=("all",), feature="chat")
    sent = await push.send_push(schedule, bots=[bot])
    assert sent == 1
    assert bot.groups == [("100", "公告")]


async def test_send_push_to_explicit_group(fresh_db):
    bot = FakeBot()
    schedule = config.PushSchedule(name="单群", text="t", targets=("999999",))
    sent = await push.send_push(schedule, bots=[bot])
    assert sent == 1
    assert bot.groups == [("999999", "t")]


def test_register_jobs_skips_disabled(tmp_path):
    settings = _load(
        tmp_path,
        '''
[[push]]
name = "早"
at = ["08:00", "20:00"]
text = "x"

[[push]]
name = "停用"
at = "09:00"
text = "y"
enabled = false
''',
    )
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    registered = push.register_jobs(scheduler, settings)
    assert registered == 2
    assert {job.id for job in scheduler.get_jobs()} == {"push:早:0", "push:早:1"}


def test_describe_reads_naturally():
    schedule = config.PushSchedule(
        name="早", text="x", times=((8, 0),), weekdays=(0, 4), targets=("all",)
    )
    line = push.describe(schedule)
    assert "08:00" in line
    assert "周一" in line and "周五" in line
    assert "全部群" in line
