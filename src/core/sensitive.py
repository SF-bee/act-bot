"""敏感词检测：纯 Python DFA(trie) 匹配 + 变体识别。

词库与转换数据（均 Apache-2.0 / MIT，见 src/core/wordlists/）：
- sensitive_word 的 6.2 万词库（houbb/sensitive-word-data，Apache-2.0）
- 繁简映射（BYVoid/OpenCC TSCharacters，Apache-2.0）
- 拼音表（mozillazg/pinyin-data，MIT），构建期用于预生成词库拼音

能力：
- 子串匹配（trie），大小写不敏感，NFKC 归一化（全角/半角）
- 可选“容忍干扰”：跳过空白/标点/符号/数字/英文字母 + 折叠连续重复字
- 可选繁简转换（繁体文本转简体后匹配）
- 可选拼音变体匹配（shuadan 这类）
- 内置 URL / 域名 / 手机号 / QQ 号 正则检测
- 白名单：命中词若落在白名单词内则忽略
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Iterable, Sequence

WORDS_DIR = Path(__file__).resolve().parent / "wordlists"
WORDS_FILE = WORDS_DIR / "sensitive_words.txt"
ALLOW_FILE = WORDS_DIR / "sensitive_allow.txt"
T2S_FILE = WORDS_DIR / "sensitive_t2s.txt"
PINYIN_FILE = WORDS_DIR / "sensitive_pinyin.txt"

_END = None  # trie 终止标记（None 不会是正常字符）

# 内置正则：URL / 域名 / 手机号 / QQ 号
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s，。！？；：、）】]+", re.IGNORECASE)
_DOMAIN_RE = re.compile(
    r"(?<![a-z0-9])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|cn|net|org|top|xyz|vip|cc|me|io|shop|club)(?![a-z0-9])",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_QQ_RE = re.compile(r"(?<!\d)[1-9]\d{5,10}(?!\d)")


def normalize(text: str) -> str:
    """NFKC 归一化 + casefold + 去掉控制/零宽字符。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text)).casefold()
    out: list[str] = []
    for ch in text:
        if unicodedata.category(ch).startswith("C"):  # 控制符 / 格式符（含零宽）
            continue
        out.append(ch)
    return "".join(out)


def _is_skip(ch: str) -> bool:
    """可被“容忍”的插入字符：空白/标点/符号/数字/ASCII 字母。

    中文汉字不跳过（否则会严重误伤）；跳过这些是为了识别 刷1单 / 刷-单 / 刷a单。
    """
    category = unicodedata.category(ch)
    if ch.isspace() or category[0] in ("P", "S", "Z", "N"):
        return True
    return category[0] == "L" and ch.isascii()


def _read_lines(path: Path) -> list[str]:
    """读取文件（以 # 开头的行为注释）。"""
    if not path.is_file():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            out.append(text)
    return out


def load_words(path: Path | None = None) -> list[str]:
    return _read_lines(path or WORDS_FILE)


def load_allow(path: Path | None = None) -> list[str]:
    return _read_lines(path or ALLOW_FILE)


def load_t2s(path: Path | None = None) -> dict[str, str]:
    """读取繁->简映射（每行：繁体 简体）。"""
    mapping: dict[str, str] = {}
    for line in _read_lines(path or T2S_FILE):
        parts = line.split()
        if len(parts) >= 2 and parts[0] != parts[1]:
            mapping[parts[0]] = parts[1]
    return mapping


def to_simplified(text: str, mapping: dict[str, str]) -> str:
    """按字符做繁->简转换（无映射时保留原字符）。"""
    if not mapping:
        return text
    return "".join(mapping.get(ch, ch) for ch in text)


class SensitiveMatcher:
    """基于 trie 的匹配器（用于敏感词或拼音词）。"""

    def __init__(self, words: Iterable[str], allow: Iterable[str] = ()) -> None:
        self._root: dict = {}
        self._allow_root: dict = {}
        self.word_count = self._build(self._root, words)
        self._build(self._allow_root, allow)

    @staticmethod
    def _build(root: dict, words: Iterable[str]) -> int:
        count = 0
        for word in words:
            norm = normalize(word)
            if not norm:
                continue
            node = root
            for ch in norm:
                node = node.setdefault(ch, {})
            if _END not in node:
                node[_END] = True
                count += 1
        return count

    @staticmethod
    def _spans(text: str, root: dict, *, skip: bool) -> list[tuple[int, int, str]]:
        """返回所有命中 (start, end, 规范化词)。

        skip=True 时容忍插入字符与连续重复字；返回的词是去掉干扰后的规范词，
        start/end 仍是原位置，用于白名单区间判断。
        """
        spans: list[tuple[int, int, str]] = []
        length = len(text)
        for start in range(length):
            stack: list[tuple[int, dict, str]] = [(start, root, "")]
            while stack:
                index, node, acc = stack.pop()
                if _END in node and index > start:
                    spans.append((start, index, acc))
                if index >= length:
                    continue
                ch = text[index]
                child = node.get(ch)
                if child is not None:
                    stack.append((index + 1, child, acc + ch))
                if skip:
                    if _is_skip(ch):
                        stack.append((index + 1, node, acc))
                    if acc and ch == acc[-1]:  # 忽略连续重复字：刷刷单 -> 刷单
                        stack.append((index + 1, node, acc))
        return spans

    def find(
        self,
        text: str,
        *,
        skip: bool = False,
        min_length: int = 2,
        t2s: dict[str, str] | None = None,
    ) -> list[str]:
        """返回命中的词（去重、保持出现顺序）。t2s 非空时先做繁->简。"""
        normalized = normalize(text)
        if t2s:
            normalized = to_simplified(normalized, t2s)
        if not normalized:
            return []
        allow_spans = (
            self._spans(normalized, self._allow_root, skip=skip) if self._allow_root else []
        )
        minimum = max(1, int(min_length))
        hits: list[str] = []
        seen: set[str] = set()
        for start, end, word in self._spans(normalized, self._root, skip=skip):
            if len(word) < minimum:
                continue
            if word in seen:
                continue
            if allow_spans and any(a <= start and end <= b for a, b, _ in allow_spans):
                continue
            seen.add(word)
            hits.append(word)
        return hits


_matcher: SensitiveMatcher | None = None
_pinyin_matcher: SensitiveMatcher | None = None
_t2s: dict[str, str] | None = None


def get_matcher() -> SensitiveMatcher:
    """进程级缓存的内置词库匹配器（首次调用加载，约 0.06s）。"""
    global _matcher
    if _matcher is None:
        _matcher = SensitiveMatcher(load_words(), load_allow())
    return _matcher


def get_pinyin_matcher() -> SensitiveMatcher:
    """进程级缓存的拼音词匹配器（仅在内置拼音开启时才会加载）。"""
    global _pinyin_matcher
    if _pinyin_matcher is None:
        _pinyin_matcher = SensitiveMatcher(_read_lines(PINYIN_FILE))
    return _pinyin_matcher


def get_t2s() -> dict[str, str]:
    """进程级缓存的繁->简映射。"""
    global _t2s
    if _t2s is None:
        _t2s = load_t2s()
    return _t2s


def reset_matcher() -> None:
    """清空全部缓存（测试 / 词库更新后用）。"""
    global _matcher, _pinyin_matcher, _t2s
    _matcher = None
    _pinyin_matcher = None
    _t2s = None


def find(
    text: str,
    *,
    skip: bool = False,
    min_length: int = 2,
    traditional: bool = False,
) -> list[str]:
    """用内置词库匹配文本；traditional=True 时先做繁->简。"""
    return get_matcher().find(
        text,
        skip=skip,
        min_length=min_length,
        t2s=get_t2s() if traditional else None,
    )


def find_pinyin(text: str, *, min_length: int = 4) -> list[str]:
    """匹配拼音变体：把文本里的连续 ASCII 字母串与“词库词的拼音”比对。"""
    normalized = normalize(text)
    if not normalized:
        return []
    compact = re.sub(r"[^a-z\u4e00-\u9fff]", "", normalized)
    runs = re.findall(r"[a-z]+", compact)
    if not runs:
        return []
    matcher = get_pinyin_matcher()
    hits: list[str] = []
    seen: set[str] = set()
    for run in runs:
        if len(run) < max(1, int(min_length)):
            continue
        for hit in matcher.find(run, min_length=min_length):
            if hit not in seen:
                seen.add(hit)
                hits.append(hit)
    return hits


def find_patterns(text: str) -> list[tuple[str, str]]:
    """内置正则检测：返回 [(kind, 命中文本)]，kind ∈ url/domain/phone/qq。"""
    raw = text or ""
    found: list[tuple[str, str, int, int]] = []
    for kind, regex in (
        ("url", _URL_RE),
        ("domain", _DOMAIN_RE),
        ("phone", _PHONE_RE),
        ("qq", _QQ_RE),
    ):
        for match in regex.finditer(raw):
            found.append((kind, match.group(0), match.start(), match.end()))
    found.sort(key=lambda item: (item[2], -(item[3] - item[2])))
    out: list[tuple[str, str]] = []
    covered: list[tuple[int, int]] = []
    seen: set[str] = set()
    for kind, match, start, end in found:
        if any(a <= start and end <= b for a, b in covered):
            continue
        covered.append((start, end))
        if match not in seen:
            seen.add(match)
            out.append((kind, match))
    return out


def word_count() -> int:
    """内置词库词数。"""
    return get_matcher().word_count
