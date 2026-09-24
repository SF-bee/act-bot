"""数据模型（SQLAlchemy）。结构基线见 ``src/core/migrations/*.sql``。"""
from .tables import (  # noqa: F401
    Admin,
    Announcement,
    ArchiveItem,
    AuditLog,
    Base,
    Department,
    Event,
    EventSignup,
    Group,
    MetaRow,
    Setting,
)

__all__ = [
    "Admin",
    "Announcement",
    "ArchiveItem",
    "AuditLog",
    "Base",
    "Department",
    "Event",
    "EventSignup",
    "Group",
    "MetaRow",
    "Setting",
]
