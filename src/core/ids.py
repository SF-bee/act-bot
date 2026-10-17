"""QQ / 群号规范化：全项目共用同一套校验口径。

规则（与历史 permissions._normalize_qq 对齐）：**纯数字且至少 MIN_ID_LEN 位**。

- 存库、比较、日志一律用规范化后的字符串，避免 "123" 与 123、带空格的 ID 混存；
- 校验失败抛 ValueError（命令层 / 脚本层转成用户可读提示）；
- 只做格式校验，不判断号码是否真实存在（那需要协议端查询）；
- 错误提示里不回显原始值的正文（QQ 号本身不算敏感，但统一用 repr 便于定位空格等笔误）。
"""
from __future__ import annotations

MIN_ID_LEN = 5


def _normalize(value: str | int, *, label: str) -> str:
    text = str(value).strip()
    if not text.isdigit() or len(text) < MIN_ID_LEN:
        raise ValueError(f"{label}格式不正确：{value!r}")
    return text


def normalize_qq(value: str | int) -> str:
    """规范化 QQ 号；非法抛 ValueError。"""
    return _normalize(value, label="QQ 号")


def normalize_group_id(value: str | int) -> str:
    """规范化群号；非法抛 ValueError。"""
    return _normalize(value, label="群号")
