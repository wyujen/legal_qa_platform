"""Query-focused, bounded RAG context construction."""

from __future__ import annotations

from collections.abc import Sequence

from legal_qa_platform.domain.legal import sha256_text
from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.domain.retrieval import ContextItem, RagContext, RetrievalResult
from legal_qa_platform.services.normalization import (
    extract_keyword_terms,
    keyword_score,
)

PRIMARY_REFERENCE_MAX_CHARS = 600
SECONDARY_REFERENCE_MAX_CHARS = 180


def _clip_around_query(text: str, question: str, limit: int) -> str:
    if limit < 1:
        raise ValueError("excerpt 字數上限必須大於零。")
    if len(text) <= limit:
        return text
    positions = [
        text.find(term)
        for term in extract_keyword_terms(question)
        if text.find(term) >= 0
    ]
    anchor = min(positions) if positions else 0
    start = max(0, anchor - limit // 4)
    end = min(len(text), start + limit)
    start = max(0, end - limit)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    available = limit - len(prefix) - len(suffix)
    if available <= 0:
        return (prefix + suffix)[:limit]
    excerpt = text[start:end].strip()[:available].strip()
    return f"{prefix}{excerpt}{suffix}"


def focused_excerpt(question: str, content: str, limit: int) -> str:
    """Preserve the legacy line ranking and query-anchored clipping behavior."""

    if not isinstance(question, str) or not isinstance(content, str):
        raise TypeError("question 與 content 必須是字串。")
    cleaned = content.strip()
    if len(cleaned) <= limit:
        return cleaned

    lines = [" ".join(line.split()) for line in cleaned.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return _clip_around_query(cleaned, question, limit)

    ranked = sorted(
        enumerate(lines),
        key=lambda pair: (-keyword_score(question, pair[1]), pair[0]),
    )
    selected: list[tuple[int, str]] = []
    used = 0
    for index, line in ranked:
        separator_size = 1 if selected else 0
        remaining = limit - used - separator_size
        if remaining <= 0:
            break
        score = keyword_score(question, line)
        if selected and score <= 0:
            break
        excerpt = _clip_around_query(line, question, remaining)
        if not excerpt:
            continue
        selected.append((index, excerpt))
        used += separator_size + len(excerpt)

    if not selected:
        return _clip_around_query(cleaned, question, limit)
    selected.sort(key=lambda pair: pair[0])
    return "\n".join(text for _, text in selected)


def build_context(
    question: str,
    retrieval_results: Sequence[RetrievalResult],
    profile: RagProfile | None = None,
) -> RagContext:
    """Build one context; ``profile.top_k`` is the sole provision-count limit."""

    if not isinstance(question, str):
        raise TypeError("question 必須是字串。")
    cleaned_question = question.strip()
    if not cleaned_question:
        raise ValueError("問題不得為空。")
    selected_profile = profile or RagProfile()
    ordered = sorted(
        retrieval_results,
        key=lambda result: (-result.final_score, result.provision_id),
    )[: selected_profile.top_k]

    items: list[ContextItem] = []
    for index, result in enumerate(ordered):
        configured_limit = (
            selected_profile.primary_context_chars
            if index == 0
            else selected_profile.secondary_context_chars
        )
        used_chars = sum(len(item.excerpt) for item in items)
        separators = len(items)
        remaining_budget = selected_profile.max_context_chars - used_chars - separators
        if remaining_budget <= 0:
            break
        limit = min(configured_limit, remaining_budget)
        excerpt = focused_excerpt(cleaned_question, result.content, limit)
        if not excerpt:
            continue
        items.append(
            ContextItem(
                provision_id=result.provision_id,
                document_name=result.document_name,
                article_no=result.article_no,
                title=result.title,
                excerpt=excerpt,
                excerpt_hash=sha256_text(excerpt),
                content_hash=result.content_hash,
                record_hash=result.record_hash,
                embedding_input_hash=result.embedding_input_hash,
                source_url=result.source_url,
                final_score=result.final_score,
                rank=len(items) + 1,
            )
        )
    return RagContext(question=cleaned_question, items=items)


build_rag_context = build_context


__all__ = [
    "PRIMARY_REFERENCE_MAX_CHARS",
    "SECONDARY_REFERENCE_MAX_CHARS",
    "build_context",
    "build_rag_context",
    "focused_excerpt",
]
