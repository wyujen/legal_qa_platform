"""Strict model-output parsing, sanitization, and local citation allowlisting."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping, Sequence
from html.parser import HTMLParser
from typing import Any

from pydantic import ValidationError

from legal_qa_platform.domain.qa import (
    LEGAL_NOTICE,
    Citation,
    LegalQaResponse,
    LLMAnswer,
)
from legal_qa_platform.domain.retrieval import RetrievalResult
from legal_qa_platform.errors import (
    ResponseValidationError as BaseResponseValidationError,
)

DEFAULT_MAX_LIST_ITEMS = 6
_DANGEROUS_BLOCK_RE = re.compile(
    r"<(?:script|style)\b[^>]*>.*?</(?:script|style)\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
_PROVISION_MARKER = r"\[\s*provision\s*id\s*=\s*\d+\s*\]"
_PROVISION_MARKER_CLUSTER_RE = re.compile(
    _PROVISION_MARKER + rf"(?:\s*(?:、|,|，|和|及|與)\s*{_PROVISION_MARKER})*",
    flags=re.IGNORECASE,
)
_PROVISION_FIELD_RE = re.compile(
    r"""["']?\bprovision[\s_-]*id\b["']?\s*[:=]\s*["']?\d+["']?""",
    flags=re.IGNORECASE,
)


class ResponseValidationError(BaseResponseValidationError):
    """The model response cannot be safely represented by the outward schema."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _strip_html(value: str) -> str:
    text = value
    for _ in range(3):
        decoded = html.unescape(text)
        without_dangerous = _DANGEROUS_BLOCK_RE.sub("", decoded)
        parser = _TextExtractor()
        try:
            parser.feed(without_dangerous)
            parser.close()
            cleaned = "".join(parser.parts)
        except Exception:
            cleaned = re.sub(r"<[^>]*>", "", without_dangerous)
        if cleaned == text:
            text = cleaned
            break
        text = cleaned

    text = html.unescape(text)
    text = _DANGEROUS_BLOCK_RE.sub("", text)
    text = re.sub(r"</?[A-Za-z][^>]*>", "", text)
    # Full-width comparison signs preserve meaning without creating HTML.
    return text.replace("<", "＜").replace(">", "＞").strip()


def sanitize_display_text(value: str) -> str:
    """Remove HTML and all internal ProvisionId representations."""

    if not isinstance(value, str):
        raise TypeError("顯示文字必須是字串。")
    text = _strip_html(value)
    text = _PROVISION_MARKER_CLUSTER_RE.sub("", text)
    text = _PROVISION_FIELD_RE.sub("", text)
    text = re.sub(r"\s+([，。；：、,.!?])", r"\1", text)
    return " ".join(text.split()).strip(" \t\r\n,，、;；:：")


def parse_structured_response(
    raw_response: str | bytes | Mapping[str, Any] | LLMAnswer,
) -> LLMAnswer:
    """Parse exactly one JSON object; never salvage prose or code fences."""

    if isinstance(raw_response, LLMAnswer):
        return raw_response
    payload: Any
    if isinstance(raw_response, bytes):
        try:
            raw_response = raw_response.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResponseValidationError("模型回傳內容不是有效的 UTF-8。") from exc

    if isinstance(raw_response, str):
        text = raw_response.strip()
        if not text:
            raise ResponseValidationError("模型回傳空內容。")
        if not text.startswith("{") or not text.endswith("}"):
            raise ResponseValidationError("模型回傳必須是單一 JSON 物件。")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ResponseValidationError("模型回傳的 JSON 格式無法解析。") from exc
    elif isinstance(raw_response, Mapping):
        payload = dict(raw_response)
    else:
        raise ResponseValidationError("模型回傳格式不受支援。")

    if not isinstance(payload, dict):
        raise ResponseValidationError("模型回傳必須是 JSON 物件。")
    try:
        return LLMAnswer.model_validate(payload)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ResponseValidationError("模型回傳內容不符合指定格式。") from exc


parse_response = parse_structured_response


def _clean_list(values: Sequence[str], maximum: int) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = sanitize_display_text(value)
        if text:
            cleaned.append(text)
        if len(cleaned) >= maximum:
            break
    return cleaned


def validate_response(
    response: str | bytes | Mapping[str, Any] | LLMAnswer,
    retrieval_results: Sequence[RetrievalResult],
    *,
    max_list_items: int = DEFAULT_MAX_LIST_ITEMS,
) -> LegalQaResponse:
    """Sanitize an answer and enrich only allowlisted citations from local data."""

    if isinstance(max_list_items, bool) or not isinstance(max_list_items, int):
        raise TypeError("列表項目數量上限必須是整數。")
    if max_list_items < 1:
        raise ValueError("列表項目數量上限必須大於零。")
    parsed = parse_structured_response(response)
    summary = sanitize_display_text(parsed.summary)
    if not summary:
        raise ResponseValidationError("模型回答的初步結論不得為空。")

    local_by_id: dict[int, RetrievalResult] = {}
    for result in retrieval_results:
        local_by_id.setdefault(result.provision_id, result)

    citations: list[Citation] = []
    seen_ids: set[int] = set()
    for selected in parsed.citations:
        provision_id = selected.provision_id
        local = local_by_id.get(provision_id)
        if local is None or provision_id in seen_ids:
            continue
        document_name = sanitize_display_text(local.document_name)
        article_no = sanitize_display_text(local.article_no)
        if not document_name or not article_no:
            continue
        seen_ids.add(provision_id)
        citations.append(
            Citation(
                provision_id=provision_id,
                document_name=document_name,
                article_no=article_no,
            )
        )
        if len(citations) >= max_list_items:
            break

    if parsed.can_answer and not citations:
        summary = "模型回答沒有可驗證的引用條文，因此無法提供受支持的初步結論。"
        conditions: list[str] = []
        exceptions: list[str] = []
        missing_information = ["請確認檢索結果是否包含足以支持結論的條文。"]
    else:
        conditions = _clean_list(parsed.conditions, max_list_items)
        exceptions = _clean_list(parsed.exceptions, max_list_items)
        missing_information = _clean_list(
            parsed.missing_information,
            max_list_items,
        )

    return LegalQaResponse(
        can_answer=bool(parsed.can_answer and citations),
        summary=summary,
        conditions=conditions,
        exceptions=exceptions,
        missing_information=missing_information,
        citations=citations,
        notice=LEGAL_NOTICE,
    )


__all__ = [
    "DEFAULT_MAX_LIST_ITEMS",
    "ResponseValidationError",
    "parse_response",
    "parse_structured_response",
    "sanitize_display_text",
    "validate_response",
]
