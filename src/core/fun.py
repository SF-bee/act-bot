"""群互动 · 骰子 / 今日运势 / 随机选择（纯逻辑，便于单测）。

设计约束：
- 不落库、不读数据库、不依赖协议端；
- 随机与「确定性运势」都集中在这里，插件只负责命令注册与门控；
- 运势按 (用户, 本地日期) 做哈希，同一人同一天结果稳定，换天/换人变化。
"""
from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass
from typing import Sequence

MAX_DICE = 20
MAX_SIDES = 1000
MAX_OPTIONS = 20
MAX_FORTUNE_TEXT = 200

# ``2d6`` / ``d20`` / ``6``（等价 1d6）；大小写 D 均可。
_DICE_SPEC = re.compile(r"^(?:(\d{1,2})?[dD])?(\d{1,4})$")
_OPTION_SPLIT = re.compile(r"[\s,，、;；]+")

_RNG = random.SystemRandom()


@dataclass(frozen=True)
class DiceResult:
    """一次掷骰结果。``spec`` 是规范化后的写法（如 ``1d6``）。"""

    spec: str
    count: int
    sides: int
    rolls: tuple[int, ...]
    total: int


@dataclass(frozen=True)
class Fortune:
    """一条今日运势。"""

    level: str
    text: str
    lucky: int


def parse_dice(spec: str) -> tuple[int, int]:
    """解析骰子表达式，返回 (数量, 面数)。

    支持 ``2d6``、``d20``、``6``（等价 1d6）。非法输入抛 ``ValueError``，
    错误文案直接面向群友。
    """
    text = str(spec or "").strip()
    match = _DICE_SPEC.fullmatch(text)
    if not match:
        raise ValueError("格式：NdM，例如 2d6、1d20（也可以只写面数，如 6）")
    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    if not 1 <= count <= MAX_DICE:
        raise ValueError(f"骰子数量需在 1–{MAX_DICE} 之间。")
    if not 2 <= sides <= MAX_SIDES:
        raise ValueError(f"骰子面数需在 2–{MAX_SIDES} 之间。")
    return count, sides


def roll_dice(spec: str, *, rng: random.Random | None = None) -> DiceResult:
    """掷骰；``rng`` 可注入（测试用），默认系统随机源。"""
    count, sides = parse_dice(spec)
    roller = rng or _RNG
    rolls = tuple(roller.randint(1, sides) for _ in range(count))
    return DiceResult(
        spec=f"{count}d{sides}",
        count=count,
        sides=sides,
        rolls=rolls,
        total=sum(rolls),
    )


def render_dice(result: DiceResult) -> str:
    """渲染掷骰结果：单颗只显示点数，多颗显示逐颗与总和。"""
    if result.count == 1:
        return f"🎲 {result.spec} 开摇！结果是：{result.rolls[0]}～"
    joined = " + ".join(str(item) for item in result.rolls)
    return f"🎲 {result.spec} 开摇！{joined} = {result.total}，合计 {result.total} 点！"


def _split_fortune(raw: str) -> tuple[str, str]:
    """把 ``等级|文案`` 拆开；没有分隔符时等级回退为「运势」。"""
    level, sep, text = str(raw).partition("|")
    if not sep:
        return "运势", str(raw).strip()
    return (level.strip() or "运势"), text.strip()


def fortune(user_id: str, *, date: str, texts: Sequence[str]) -> Fortune:
    """按 (用户, 日期) 生成确定性运势。

    同一用户同一天多次调用结果完全一致；换一天或换一个人都可能变化。
    ``texts`` 每项形如 ``"大吉|{nickname} 今天……"``。
    """
    items = [str(item) for item in texts if str(item).strip()]
    if not items:
        raise ValueError("运势文案未配置")
    digest = hashlib.sha256(f"{date}:{user_id}".encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % len(items)
    lucky = int.from_bytes(digest[4:8], "big") % 99 + 1
    level, text = _split_fortune(items[index])
    return Fortune(level=level, text=text, lucky=lucky)


def render_fortune(result: Fortune, *, nickname: str, date: str) -> str:
    """渲染运势；未识别的占位符原样保留（与签到模板一致）。"""
    text = str(result.text).replace("{nickname}", str(nickname)).replace("{date}", str(date))
    return (
        f"🔮 {nickname} 的今日运势：{result.level}！\n"
        f"{text}\n"
        f"✨ 幸运数字：{result.lucky}，接住今天的小惊喜吧！"
    )


def parse_options(raw: str) -> list[str]:
    """把 ``/选一个`` 的参数拆成选项：空格 / 逗号 / 顿号 / 分号均可分隔。"""
    return [item for item in _OPTION_SPLIT.split(str(raw or "").strip()) if item]


def choose(options: Sequence[str], *, rng: random.Random | None = None) -> str:
    """从 2–20 个选项里随机选一个；数量不合法抛 ``ValueError``。"""
    items = [str(item).strip() for item in options if str(item).strip()]
    if len(items) < 2:
        raise ValueError("至少给两个选项，例如：/选一个 火锅 烤肉 拉面")
    if len(items) > MAX_OPTIONS:
        raise ValueError(f"选项最多 {MAX_OPTIONS} 个。")
    return (rng or _RNG).choice(items)
