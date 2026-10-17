"""SQLAlchemy 模型：与 ``src/core/migrations/*.sql`` 保持同步（SQL 是结构基线）。"""
from __future__ import annotations

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MetaRow(Base):
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[str] = mapped_column(String, default="")


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    qq: Mapped[str] = mapped_column(String, unique=True)
    role: Mapped[str] = mapped_column(String, default="admin")
    note: Mapped[str] = mapped_column(String, default="")
    created_by: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, default="")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String, default="")
    # 群级功能开关：JSON 文本，形如 {"welcome": true, "chat": false}
    features: Mapped[str] = mapped_column(Text, default="{}")
    active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String, default="")


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    contact: Mapped[str] = mapped_column(String, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[int] = mapped_column(Integer, default=1)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String, default="")
    start_at: Mapped[str] = mapped_column(String, default="")
    end_at: Mapped[str] = mapped_column(String, default="")
    signup_required: Mapped[int] = mapped_column(Integer, default=0)
    signup_deadline: Mapped[str] = mapped_column(String, default="")
    capacity: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="draft")
    created_by: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, default="")


class EventSignup(Base):
    __tablename__ = "event_signups"
    __table_args__ = (UniqueConstraint("event_id", "qq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(Integer)
    qq: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String, default="")
    note: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="going")
    created_at: Mapped[str] = mapped_column(String, default="")


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, default="")
    content: Mapped[str] = mapped_column(Text)
    target_groups: Mapped[str] = mapped_column(Text, default="[]")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="draft")
    created_by: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, default="")
    sent_at: Mapped[str] = mapped_column(String, default="")


class ArchiveItem(Base):
    __tablename__ = "archive_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String, default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authors: Mapped[str] = mapped_column(String, default="")
    dept_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    file_path: Mapped[str] = mapped_column(String, default="")
    url: Mapped[str] = mapped_column(String, default="")
    tags: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, default="")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[str] = mapped_column(String, default="")
    updated_by: Mapped[str] = mapped_column(String, default="")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    qq: Mapped[str] = mapped_column(String, default="")
    action: Mapped[str] = mapped_column(String)
    detail: Mapped[str] = mapped_column(Text, default="")
    # 操作发生在哪个群；全局操作留空（迁移 002 增加）
    group_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, default="")


class ChatRule(Base):
    """聊天引擎规则（迁移 003）：keyword / regex / mention / mention_more / mention_tired。

    ``group_id`` 为空串表示全局默认规则；群级规则覆盖同 kind 的全局规则。
    """

    __tablename__ = "chat_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String, default="")
    kind: Mapped[str] = mapped_column(String, default="keyword")
    pattern: Mapped[str] = mapped_column(String, default="")
    reply: Mapped[str] = mapped_column(Text)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, default="")


class StatsDaily(Base):
    """每日统计（迁移 004）：按 群 + 日期 + 指标 存一行；group_id 为空表示全局。"""

    __tablename__ = "stats_daily"

    group_id: Mapped[str] = mapped_column(String, primary_key=True, default="")
    date: Mapped[str] = mapped_column(String, primary_key=True, default="")
    metric: Mapped[str] = mapped_column(String, primary_key=True, default="")
    value: Mapped[int] = mapped_column(Integer, default=0)


class AdminBinding(Base):
    """私聊管理群的默认群绑定（迁移 006）：qq -> group_id，重启后保留。"""

    __tablename__ = "admin_bindings"

    qq: Mapped[str] = mapped_column(String, primary_key=True)
    group_id: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[str] = mapped_column(String, default="")


class ModerationRule(Base):
    """群风控规则（迁移 005）：敏感词/正则 → 撤回/警告/禁言/踢出。

    group_id 为空串表示全局规则；全局与群级叠加生效。
    """

    __tablename__ = "moderation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String, default="")
    kind: Mapped[str] = mapped_column(String, default="keyword")
    pattern: Mapped[str] = mapped_column(String, default="")
    action: Mapped[str] = mapped_column(String, default="warn")
    recall: Mapped[int] = mapped_column(Integer, default=1)
    mute_seconds: Mapped[int] = mapped_column(Integer, default=600)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(String, default="")
    created_by: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, default="")


class Checkin(Base):
    """群签到（迁移 007）：一人一天一条，复合主键天然防重复。"""

    __tablename__ = "checkins"

    group_id: Mapped[str] = mapped_column(String, primary_key=True, default="")
    user_id: Mapped[str] = mapped_column(String, primary_key=True, default="")
    date: Mapped[str] = mapped_column(String, primary_key=True, default="")
    # 签到当时的群昵称快照（榜单直接用；空则打码 QQ）
    display_name: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, default="")
