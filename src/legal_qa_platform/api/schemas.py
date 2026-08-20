"""Framework-neutral REST request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from legal_qa_platform.domain.qa import QuestionText
from legal_qa_platform.domain.retrieval import RetrievalResult


class RetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    message: QuestionText
    profile: str = Field(default="platform-baseline-v1", min_length=1, max_length=128)


class RetrieveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    question: str
    normalized_question: str
    profile: str
    retrieval_results: list[RetrievalResult]
    stage_latencies_ms: dict[str, float] = Field(default_factory=dict)
    duration_ms: int = Field(strict=True, ge=0)


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    query_id: str = Field(min_length=1, max_length=128)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    rating: int | None = Field(default=None, strict=True)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    comment: str | None = Field(default=None, min_length=1, max_length=4_000)


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    feedback_id: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: str
    service: str


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: str
    checks: dict[str, bool]


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    error: str
    category: str


__all__ = [
    "ErrorResponse",
    "FeedbackRequest",
    "FeedbackResponse",
    "HealthResponse",
    "ReadinessResponse",
    "RetrieveRequest",
    "RetrieveResponse",
]
