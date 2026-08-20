"""Strict question-bank, LLM-boundary, and outward QA API models."""

from __future__ import annotations

import unicodedata
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from legal_qa_platform.domain.retrieval import RetrievalResult

LEGAL_NOTICE = "本回答僅供內部初步法規解析，不構成正式法律意見。"

QuestionId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
QuestionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
]
ExpectedAnswer = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000),
]
DocumentName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
ArticleNo = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
ExpectedKeyword = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
AnswerText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000),
]
AnswerListItem = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
]


def _normalized_unique_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


class QuestionBankItem(BaseModel):
    """One validated offline evaluation case; never included in a live prompt."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        frozen=True,
    )

    question_id: QuestionId
    question: QuestionText
    expected_answer: ExpectedAnswer
    expected_keywords: list[ExpectedKeyword] = Field(min_length=1, max_length=100)
    expected_provision_ids: list[int] = Field(min_length=1, max_length=100)
    document_name: DocumentName
    article_no: ArticleNo

    @field_validator("expected_provision_ids")
    @classmethod
    def validate_provision_ids(cls, values: list[int]) -> list[int]:
        if any(isinstance(value, bool) or value <= 0 for value in values):
            raise ValueError("expected_provision_ids 必須是正整數。")
        if len(values) != len(set(values)):
            raise ValueError("expected_provision_ids 不可包含重複項目。")
        return values

    @field_validator("expected_keywords")
    @classmethod
    def validate_keywords(cls, values: list[str]) -> list[str]:
        normalized = [_normalized_unique_text(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("expected_keywords 不可包含重複項目。")
        return values


class LLMCitation(BaseModel):
    """The only citation data the untrusted model is allowed to choose."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provision_id: int = Field(strict=True, gt=0)


class LLMAnswer(BaseModel):
    """Exact structured-output DTO accepted from the model gateway."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        frozen=True,
        json_schema_extra={"additionalProperties": False},
    )

    can_answer: bool = Field(strict=True)
    summary: AnswerText
    conditions: list[AnswerListItem]
    exceptions: list[AnswerListItem]
    missing_information: list[AnswerListItem]
    citations: list[LLMCitation]


class Citation(BaseModel):
    """A model-selected ID enriched only from trusted local retrieval data."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        frozen=True,
    )

    provision_id: int = Field(strict=True, gt=0)
    document_name: DocumentName
    article_no: ArticleNo


class LegalQaResponse(BaseModel):
    """Sanitized outward response suitable for API and UI serialization."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        frozen=True,
    )

    can_answer: bool = Field(strict=True)
    summary: AnswerText
    conditions: list[AnswerListItem] = Field(default_factory=list)
    exceptions: list[AnswerListItem] = Field(default_factory=list)
    missing_information: list[AnswerListItem] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    notice: str = LEGAL_NOTICE

    @field_validator("notice")
    @classmethod
    def validate_fixed_notice(cls, value: str) -> str:
        if value != LEGAL_NOTICE:
            raise ValueError("notice 必須使用本地固定免責文字。")
        return value


class ChatRequest(BaseModel):
    """Framework-neutral input contract for ``POST /api/v1/chat``."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        frozen=True,
    )

    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: QuestionText
    profile: str = Field(default="platform-baseline-v1", min_length=1, max_length=128)


class ChatResponse(BaseModel):
    """Framework-neutral outward envelope for one QA application run."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        frozen=True,
    )

    query_id: str = Field(min_length=1, max_length=128)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    question: QuestionText
    normalized_question: QuestionText
    profile: str = Field(min_length=1, max_length=128)
    response: LegalQaResponse | None = None
    retrieval_results: list[RetrievalResult] = Field(default_factory=list)
    stage_latencies_ms: dict[str, float] = Field(default_factory=dict)
    duration_ms: int = Field(default=0, strict=True, ge=0)
    error: str | None = None


# Compatibility names ease the migration without preserving old infrastructure.
QaTestQuestion = QuestionBankItem
LegalQaResult = ChatResponse
QaApiResponse = ChatResponse


__all__ = [
    "Citation",
    "ChatRequest",
    "ChatResponse",
    "LEGAL_NOTICE",
    "LLMAnswer",
    "LLMCitation",
    "LegalQaResponse",
    "LegalQaResult",
    "QaApiResponse",
    "QaTestQuestion",
    "QuestionBankItem",
]
