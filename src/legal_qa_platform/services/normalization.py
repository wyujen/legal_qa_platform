"""Deterministic Traditional-Chinese query and keyword normalization."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from types import MappingProxyType

from legal_qa_platform.domain.legal import LegalProvision

NORMALIZATION_VERSION = "legal_qa_platform-normalization-v1"

DEFAULT_SYNONYMS: Mapping[str, str] = MappingProxyType(
    {
        "補資料": "補件",
        "逾期": "超過期限",
        "老師": "教師",
    }
)

_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "。": ".",
        "、": ",",
        "；": ";",
        "：": ":",
        "？": "?",
        "！": "!",
        "「": '"',
        "」": '"',
        "『": '"',
        "』": '"',
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "…": "...",
        "—": "-",
        "–": "-",
    }
)
_WHITESPACE_RE = re.compile(r"\s+")
_ARTICLE_RE = re.compile(
    r"第\s*[0-9０-９零〇一二三四五六七八九十百千兩两之\-－]+\s*條"
    r"(?:\s*之\s*[0-9０-９零〇一二三四五六七八九十]+)?"
)
_LEXICAL_RE = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+")
_LOW_INFORMATION_TERMS = frozenset(
    {
        "可以",
        "是否",
        "什麼",
        "何謂",
        "如何",
        "怎麼",
        "哪些",
        "哪個",
        "請問",
        "規定",
        "依據",
        "法律",
        "問題",
    }
)


def _normalize_characters(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.translate(_PUNCTUATION_TRANSLATION)
    normalized = normalized.lower()
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def _replace_synonyms(text: str, synonyms: Mapping[str, str]) -> str:
    normalized_synonyms: dict[str, str] = {}
    for source, target in synonyms.items():
        if not isinstance(source, str) or not isinstance(target, str):
            raise TypeError("同義詞的來源與目標都必須是字串。")
        normalized_source = _normalize_characters(source)
        if normalized_source:
            normalized_synonyms[normalized_source] = _normalize_characters(target)

    if not normalized_synonyms:
        return text
    pattern = re.compile(
        "|".join(
            re.escape(source)
            for source in sorted(normalized_synonyms, key=len, reverse=True)
        )
    )
    # A single regex pass prevents replacement results from being replaced again.
    return pattern.sub(lambda match: normalized_synonyms[match.group(0)], text)


def normalize_text(
    text: str,
    synonyms: Mapping[str, str] | None = None,
) -> str:
    """Apply the preserved NFKC, punctuation, case, whitespace, and synonym rules."""

    if not isinstance(text, str):
        raise TypeError("待正規化內容必須是字串。")
    normalized = _normalize_characters(text)
    selected = DEFAULT_SYNONYMS if synonyms is None else synonyms
    return _replace_synonyms(normalized, selected)


normalize = normalize_text


def _normalize_keyword_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("關鍵字內容必須是字串。")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def compact_keyword_text(value: str) -> str:
    """Return the compact representation shared with PostgreSQL retrieval."""

    return re.sub(r"[^\w\u3400-\u9fff]+", "", _normalize_keyword_text(value))


def extract_keyword_terms(query: str) -> set[str]:
    """Extract article phrases, Latin tokens, and Chinese bigrams exactly once."""

    normalized = _normalize_keyword_text(query)
    terms: set[str] = set()

    for match in _ARTICLE_RE.finditer(normalized):
        terms.add(re.sub(r"\s+", "", match.group(0)))

    for token in _LEXICAL_RE.findall(normalized):
        if re.fullmatch(r"[a-z0-9]+", token):
            if token not in _LOW_INFORMATION_TERMS:
                terms.add(token)
            continue
        if len(token) == 1:
            continue
        if len(token) == 2:
            if token not in _LOW_INFORMATION_TERMS:
                terms.add(token)
            continue
        for index in range(len(token) - 1):
            bigram = token[index : index + 2]
            if bigram not in _LOW_INFORMATION_TERMS:
                terms.add(bigram)
    return terms


def keyword_score(query: str, searchable_text: str) -> float:
    """Return complete-phrase 1.0 or matched-query-terms/query-terms."""

    normalized_query = _normalize_keyword_text(query)
    normalized_text = _normalize_keyword_text(searchable_text)
    if not normalized_query or not normalized_text:
        return 0.0

    compact_query = compact_keyword_text(normalized_query)
    compact_text = compact_keyword_text(normalized_text)
    if compact_query and compact_query in compact_text:
        return 1.0

    terms = extract_keyword_terms(normalized_query)
    if not terms:
        return 0.0
    matched = sum(term in compact_text for term in terms)
    return matched / len(terms)


def provision_search_text(provision: LegalProvision) -> str:
    """Return all human-visible fields when no prepared search text exists."""

    if provision.search_text:
        return provision.search_text
    return " ".join(
        part
        for part in (
            provision.document_name,
            provision.chapter_name,
            provision.section_name,
            provision.article_no,
            provision.title,
            provision.content,
        )
        if part
    )


__all__ = [
    "DEFAULT_SYNONYMS",
    "NORMALIZATION_VERSION",
    "compact_keyword_text",
    "extract_keyword_terms",
    "keyword_score",
    "normalize",
    "normalize_text",
    "provision_search_text",
]
