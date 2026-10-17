"""日志脱敏：只保留可关联的「形状」与指纹，不落消息正文。

背景：systemd journal / NSSM / Docker 日志会长期留存，正文（哪怕截断）一旦进日志
就违背「统计不保存消息正文」的口径。需要把同一条消息的多行日志串起来时用指纹。
"""
from __future__ import annotations

import hashlib


def fingerprint(text: str, *, length: int = 8) -> str:
    """正文的 sha256 前 N 位（空串返回 "-"）；仅用于关联，不能反推正文。"""
    body = text or ""
    if not body:
        return "-"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[: max(1, int(length))]


def shape(text: str) -> str:
    """正文长度，形如 "len=37"（保留「长消息」信号，不保留内容）。"""
    return "len={0}".format(len(text or ""))
