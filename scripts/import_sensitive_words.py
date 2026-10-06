#!/usr/bin/env python3
"""从 houbb/sensitive-word-data 生成内置敏感词库（默认排除政治类 tag 0）。

用法：
    uv run python scripts/import_sensitive_words.py [--ref main] [--exclude-tags 0] [--min-length 2]

数据来源：https://github.com/houbb/sensitive-word-data （Apache-2.0，词库自带标签）
产物：
    src/core/wordlists/sensitive_words.txt   内置黑名单（已过滤）
    src/core/wordlists/sensitive_allow.txt   白名单
说明：这是维护脚本，需要联网，不在 CI 里跑；生成结果提交进仓库。
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "src" / "core" / "wordlists"
BASE = "https://raw.githubusercontent.com/houbb/sensitive-word-data/{ref}/src/main/resources/{name}"
DICT = "sensitive_word_dict.txt"
DICT_EN = "sensitive_word_dict_en.txt"
TAGS = "sensitive_word_tags.txt"
ALLOW = "sensitive_word_allow.txt"
OPENCC_T2S_URL = "https://raw.githubusercontent.com/BYVoid/OpenCC/master/data/dictionary/TSCharacters.txt"
PINYIN_DATA_URL = "https://raw.githubusercontent.com/mozillazg/pinyin-data/master/pinyin.txt"
PINYIN_MAX_WORD_LEN = 4

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - 固定上游地址
        return resp.read().decode("utf-8", errors="ignore")


def _strip_tones(pinyin: str) -> str:
    """去掉拼音音调并归一（ü -> v）。"""
    decomposed = unicodedata.normalize("NFD", pinyin)
    out = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return out.replace("ü", "v").replace("u:", "v").lower()


def parse_pinyin(text: str) -> dict[str, str]:
    """解析 pinyin-data：U+XXXX: p1,p2  # 字 -> 字: 首个读音（无音调）。"""
    mapping: dict[str, str] = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        code, readings = line.split(":", 1)
        code = code.strip().upper()
        if not code.startswith("U+"):
            continue
        try:
            char = chr(int(code[2:], 16))
        except ValueError:
            continue
        first = readings.strip().split(",")[0].strip()
        if first:
            mapping[char] = _strip_tones(first)
    return mapping


def parse_tags(text: str) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        word, raw = parts
        mapping[word] = {tag.strip() for tag in raw.split(",") if tag.strip()}
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="生成内置敏感词库")
    parser.add_argument("--ref", default="main", help="上游分支/标签")
    parser.add_argument("--exclude-tags", default="0", help="排除的标签（逗号分隔，0=政治）")
    parser.add_argument("--min-length", type=int, default=2, help="最短词长（默认 2，过滤单字）")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    excluded = {tag.strip() for tag in str(args.exclude_tags).split(",") if tag.strip()}
    print("上游：houbb/sensitive-word-data @", args.ref)
    print("排除标签：", sorted(excluded) or "（无）")

    words_text = fetch(BASE.format(ref=args.ref, name=DICT))
    tags_text = fetch(BASE.format(ref=args.ref, name=TAGS))
    allow_text = fetch(BASE.format(ref=args.ref, name=ALLOW))
    try:
        words_en = fetch(BASE.format(ref=args.ref, name=DICT_EN))
    except Exception:  # noqa: BLE001 - 英文词库可选
        words_en = ""

    tags = parse_tags(tags_text)
    seen: set[str] = set()
    kept: list[str] = []
    dropped_tag = 0
    dropped_short = 0
    for raw in (words_text + "\n" + words_en).splitlines():
        word = raw.strip()
        if not word or word.startswith("#") or word in seen:
            continue
        seen.add(word)
        word_tags = tags.get(word, set())
        if word_tags & excluded:
            dropped_tag += 1
            continue
        if len(word) < max(1, int(args.min_length)):
            dropped_short += 1
            continue
        kept.append(word)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    header = (
        "# ACT Bot 内置敏感词库（自动生成，请勿手改）\n"
        "# 来源：https://github.com/houbb/sensitive-word-data （Apache-2.0）\n"
        "# 生成：uv run python scripts/import_sensitive_words.py --ref {ref} --exclude-tags {excl}\n"
        "# 排除标签：{excl}（0=政治）｜词数：{count}\n"
    ).format(ref=args.ref, excl=",".join(sorted(excluded)) or "-", count=len(kept))
    (out_dir / "sensitive_words.txt").write_text(header + "\n".join(kept) + "\n", encoding="utf-8")

    allow_words = [line.strip() for line in allow_text.splitlines() if line.strip()]
    (out_dir / "sensitive_allow.txt").write_text("\n".join(allow_words) + "\n", encoding="utf-8")

    # 繁 -> 简 映射（OpenCC TSCharacters，Apache-2.0）
    t2s_lines: list[str] = []
    for line in fetch(OPENCC_T2S_URL).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] != parts[1]:
            t2s_lines.append(parts[0] + " " + parts[1])
    (out_dir / "sensitive_t2s.txt").write_text(
        "# 繁 -> 简 映射，来源 OpenCC TSCharacters.txt（Apache-2.0）\n"
        + "\n".join(t2s_lines)
        + "\n",
        encoding="utf-8",
    )

    # 词库词的拼音变体（pinyin-data，MIT）：仅 <=4 字词，运行时按需加载
    pinyin_map = parse_pinyin(fetch(PINYIN_DATA_URL))
    pinyin_words: list[str] = []
    for word in kept:
        if len(word) > PINYIN_MAX_WORD_LEN:
            continue
        parts = [pinyin_map.get(ch) for ch in word]
        if not parts or any(part is None for part in parts):
            continue
        full = "".join(parts)
        if len(full) >= 3:
            pinyin_words.append(full)
    pinyin_words = sorted(set(pinyin_words))
    (out_dir / "sensitive_pinyin.txt").write_text(
        "# 词库词的拼音（无音调，仅 <=4 字词），来源 pinyin-data（MIT）｜{0} 条\n".format(len(pinyin_words))
        + "\n".join(pinyin_words)
        + "\n",
        encoding="utf-8",
    )

    print("保留词数：{0}（排除标签 {1}，太短 {2}）".format(len(kept), dropped_tag, dropped_short))
    print("繁简映射：{0} 条；拼音变体：{1} 条".format(len(t2s_lines), len(pinyin_words)))
    print("白名单：{0} 条".format(len(allow_words)))
    print("输出目录：", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
