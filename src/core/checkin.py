"""签到：群互动 · 打卡与签到榜。

口径与自我约束：
- **一人一天一条**（主键 group_id + user_id + date）；重复签到靠主键冲突识别，
  不做「先查后写」的乐观假设；
- 连续天数从最近一次签到往前逐日回溯，最多回看 MAX_STREAK_LOOKBACK 天；
- 累计次数 = 该群该人的签到总条数；
- 榜单默认本月，可切累计；昵称用**签到当时的快照**（省掉为榜单逐个查协议端），
  快照为空则用 src.core.stats.mask_qq 打码；
- 不存消息正文、不存聊天记录，只有日期 + 昵称快照。

分层：签到 / 榜单 / 渲染都在这里，命令注册与权限判定在 src/plugins/checkin/。
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date as _date
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.core import db, stats
from src.core.ids import normalize_group_id, normalize_qq
from src.core.config import AppSettings, get_settings
from src.core.db import utc_now
from src.models.tables import Checkin

logger = logging.getLogger("actbot.checkin")

DEFAULT_TZ = stats.DEFAULT_TZ

STATUS_OK = "ok"
STATUS_REPEAT = "repeat"

SCOPE_MONTH = "month"
SCOPE_ALL = "all"
SCOPE_LABELS = {SCOPE_MONTH: "本月", SCOPE_ALL: "累计"}

# 连续天数最多回看多少天（防止历史很长的账号一次拉太多行）
MAX_STREAK_LOOKBACK = 400

# 里程碑：累计次数命中这些值时额外道贺（文案见 [checkin].milestone_text）
MILESTONES = (7, 30, 100, 365)

_SCOPE_MONTH_WORDS = ("", "本月", "这个月", "这月", "当月", "month", "this month")
_SCOPE_ALL_WORDS = ("总", "累计", "总共", "全部", "所有", "all", "total")


@dataclass(frozen=True)
class CheckinResult:
    """一次签到的结果（重复签到同样返回，便于文案区分）。"""

    status: str
    date: str
    streak: int
    total: int
    rank_today: int
    milestone: int = 0

    @property
    def repeated(self) -> bool:
        """今天是否已经签过（重复签到不覆盖、不报错）。"""
        return self.status == STATUS_REPEAT


@dataclass(frozen=True)
class LeaderRow:
    """签到榜的一行。name 已做过空值回退（打码 QQ）。"""

    user_id: str
    name: str
    count: int
    last_date: str


def parse_scope(argument: str) -> str:
    """解析榜单范围参数；无法识别抛 ValueError（调用方给用法提示）。"""
    text = str(argument or "").strip().lower()
    if text in _SCOPE_MONTH_WORDS:
        return SCOPE_MONTH
    if text in _SCOPE_ALL_WORDS:
        return SCOPE_ALL
    raise ValueError("无法识别的榜单范围：{0!r}".format(argument))


def _day(value: str) -> _date:
    return _date.fromisoformat(str(value))


async def _streak(session, group_id: str, user_id: str, day: str) -> int:
    """从 day 往前逐日回溯的连续签到天数（假定 day 当天已签到）。"""
    rows = (
        await session.execute(
            select(Checkin.date)
            .where(Checkin.group_id == group_id, Checkin.user_id == user_id)
            .order_by(Checkin.date.desc())
            .limit(MAX_STREAK_LOOKBACK)
        )
    ).scalars().all()
    expected = _day(day)
    count = 0
    for item in rows:
        if _day(str(item)) != expected:
            break
        count += 1
        expected -= timedelta(days=1)
    return count


async def check_in(
    group_id: str | int,
    user_id: str | int,
    *,
    display_name: str = "",
    date: str | None = None,
    tz_name: str = DEFAULT_TZ,
) -> CheckinResult:
    """签到一次；当天已签过则返回 status="repeat"（幂等，不覆盖已有记录）。"""
    gid, uid = normalize_group_id(group_id), normalize_qq(user_id)
    day = str(date) if date else stats.today(tz_name)
    async with db.get_session() as session:
        existing = (
            await session.execute(
                select(Checkin).where(
                    Checkin.group_id == gid,
                    Checkin.user_id == uid,
                    Checkin.date == day,
                )
            )
        ).scalar_one_or_none()
        status = STATUS_REPEAT if existing is not None else STATUS_OK
        if existing is None:
            session.add(
                Checkin(
                    group_id=gid,
                    user_id=uid,
                    date=day,
                    display_name=str(display_name or "").strip(),
                    created_at=utc_now(),
                )
            )
            try:
                await session.commit()
            except IntegrityError:  # 同一瞬间的并发签到：主键挡住了，按已签过处理
                await session.rollback()
                status = STATUS_REPEAT
        rank_today = int(
            await session.scalar(
                select(func.count(func.distinct(Checkin.user_id))).where(
                    Checkin.group_id == gid, Checkin.date == day
                )
            )
            or 0
        )
        streak = await _streak(session, gid, uid, day)
        total = int(
            await session.scalar(
                select(func.count())
                .select_from(Checkin)
                .where(Checkin.group_id == gid, Checkin.user_id == uid)
            )
            or 0
        )
    milestone = total if status == STATUS_OK and total in MILESTONES else 0
    return CheckinResult(
        status=status,
        date=day,
        streak=streak,
        total=total,
        rank_today=rank_today,
        milestone=milestone,
    )


async def leaderboard(
    group_id: str | int,
    *,
    scope: str = SCOPE_MONTH,
    limit: int = 10,
    date: str | None = None,
    tz_name: str = DEFAULT_TZ,
) -> list[LeaderRow]:
    """签到榜：按签到次数倒序，同次数先达标者靠前（MAX(date) 更早）。"""
    gid = normalize_group_id(group_id)
    count = func.count().label("cnt")
    last = func.max(Checkin.date).label("last")
    where: list[Any] = [Checkin.group_id == gid]
    if scope != SCOPE_ALL:
        day = str(date) if date else stats.today(tz_name)
        where.append(Checkin.date >= day[:8] + "01")

    async with db.get_session() as session:
        rows = (
            await session.execute(
                select(Checkin.user_id, count, last)
                .where(*where)
                .group_by(Checkin.user_id)
                .order_by(count.desc(), last.asc())
                .limit(max(1, int(limit)))
            )
        ).all()
        if not rows:
            return []
        ids = [str(row[0]) for row in rows]
        names: dict[str, str] = {}
        for user_id, _, display_name in (
            await session.execute(
                select(Checkin.user_id, Checkin.date, Checkin.display_name)
                .where(Checkin.group_id == gid, Checkin.user_id.in_(ids))
                .order_by(Checkin.date.asc())
            )
        ).all():
            label = str(display_name or "").strip()
            if label:  # 按日期升序遍历，最后写入的就是最近一次的快照
                names[str(user_id)] = label
    return [
        LeaderRow(
            user_id=str(row[0]),
            name=names.get(str(row[0])) or stats.mask_qq(str(row[0])),
            count=int(row[1]),
            last_date=str(row[2] or ""),
        )
        for row in rows
    ]


class _SafeValues(dict):
    """模板占位符字典：未知键原样保留 {key}，不让配置笔误打断签到。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _format(template: str, values: Mapping[str, Any]) -> str:
    try:
        return str(template).format_map(_SafeValues(values))
    except (ValueError, IndexError):  # 花括号写崩了也不抛给群友
        return str(template)


def render_checkin(
    result: CheckinResult,
    *,
    nickname: str,
    group_name: str = "",
    bot_name: str = "",
    bot_title: str = "",
    settings: AppSettings | None = None,
) -> str:
    """按结果挑模板渲染签到回复（日常 / 重复 / 里程碑）。"""
    cfg = settings or get_settings()
    values = {
        "nickname": nickname or "群友",
        "date": result.date,
        "streak": result.streak,
        "total": result.total,
        "rank": result.rank_today,
        "milestone": result.milestone,
        "group_name": group_name,
        "bot_name": bot_name,
        "bot_title": bot_title,
    }
    if result.repeated:
        template = cfg.checkin_repeat_text
    elif result.milestone:
        template = cfg.checkin_milestone_text
    else:
        template = cfg.checkin_daily_text
    return _format(template, values)


def render_leaderboard(
    rows: Sequence[LeaderRow],
    *,
    scope: str = SCOPE_MONTH,
    group_name: str = "",
    bot_name: str = "",
    bot_title: str = "",
) -> str:
    """渲染签到榜（空榜提示由调用方负责）。"""
    who = "{0}（{1}）· ".format(bot_name, bot_title) if bot_name else ""
    where = "「{0}」".format(group_name) if group_name else ""
    lines = ["{0}{1}签到榜（{2}）".format(who, where, SCOPE_LABELS.get(scope, scope))]
    for index, row in enumerate(rows, start=1):
        lines.append("{0}. {1} · {2} 次".format(index, row.name, row.count))
    lines.append("共 {0} 人上榜".format(len(rows)))
    return "\n".join(lines)
