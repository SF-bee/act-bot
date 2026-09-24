"""规则守护测试：跨平台禁令扫描（业务代码不得出现平台分支 / 系统特定调用）。

允许例外：本文件自身（模式定义处）以及注释中带 ``platform-ok`` 标记的行。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [ROOT / "src", ROOT / "scripts"]
SELF = Path(__file__).resolve()

# 通过拼接构造模式，避免本文件自我命中
FORBIDDEN = [
    "/home" + "/",
    "C:" + "\\",
    "uv" + "loop",
    "shell" + "=True",
    "os" + ".system(",
    "os" + ".chmod",
    "os" + ".fork",
    "sys" + ".platform",
    "os" + ".name",
    "/Users" + "/",
]


def _iter_py_files():
    for base in SCAN_DIRS:
        yield from base.rglob("*.py")


def test_no_platform_specific_patterns():
    hits: list[str] = []
    for file in _iter_py_files():
        if file.resolve() == SELF:
            continue
        text = file.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "platform-ok" in line:
                continue
            for pattern in FORBIDDEN:
                if pattern in line:
                    hits.append(
                        f"{file.relative_to(ROOT)}:{lineno}: {line.strip()[:90]}  ← 命中 {pattern!r}"
                    )
    assert not hits, "发现跨平台禁令命中：\n" + "\n".join(hits)
