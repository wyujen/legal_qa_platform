"""Strict, provider-neutral retrieval and RAG-context DTOs."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from legal_qa_platform.domain.legal import Sha256Hex


class RetrievalCandidate(BaseModel):
    """A lightweight hit returned by either candidate source."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provision_id: int = Field(strict=True, gt=0)
    score: float = Field(allow_inf_nan=False)


class RetrievalResult(BaseModel):
    """Locally enriched hybrid result returned by the application core."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        frozen=True,
    )

    provision_id: int = Field(strict=True, gt=0)
    document_name: str = Field(min_length=1)
    article_no: str = Field(min_length=1)
    title: str = ""
    content: str = Field(min_length=1)
    source_url: str = ""
    content_hash: Sha256Hex
    record_hash: Sha256Hex
    embedding_input_hash: Sha256Hex
    vector_score: float = Field(allow_inf_nan=False)
    keyword_score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    final_score: float = Field(allow_inf_nan=False)
    rank: int = Field(strict=True, ge=1)


class ContextItem(BaseModel):
    """A query-focused, bounded excerpt derived from one retrieval result."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        frozen=True,
    )

    provision_id: int = Field(strict=True, gt=0)
    document_name: str = Field(min_length=1)
    article_no: str = Field(min_length=1)
    title: str = ""
    excerpt: str = Field(min_length=1)
    excerpt_hash: Sha256Hex
    content_hash: Sha256Hex
    record_hash: Sha256Hex
    embedding_input_hash: Sha256Hex
    source_url: str = ""
    final_score: float = Field(allow_inf_nan=False)
    rank: int = Field(strict=True, ge=1)


class RagContext(BaseModel):
    """The complete RAG context for one normalized question."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        frozen=True,
    )

    question: Annotated[str, StringConstraints(min_length=1)]
    items: list[ContextItem] = Field(default_factory=list)


__all__ = [
    "ContextItem",
    "RagContext",
    "RetrievalCandidate",
    "RetrievalResult",
]
