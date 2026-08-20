"""Validated RAG experiment profile shared by every application entry point."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_VECTOR_WEIGHT = 0.65
DEFAULT_KEYWORD_WEIGHT = 0.35


class RagProfile(BaseModel):
    """All baseline retrieval/model choices that are safe to experiment with."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        frozen=True,
    )

    name: str = Field(default="platform-baseline-v1", min_length=1)
    chat_model: str = Field(default="campus-qa", min_length=1)
    embedding_model: str = Field(default="bge-m3", min_length=1)
    embedding_dimension: int = Field(default=1_024, strict=True, ge=1, le=65_536)
    vector_collection: str = Field(
        default="legal_provisions_bge_m3_v1",
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    candidate_k: int = Field(default=50, strict=True, ge=1, le=1_000)
    top_k: int = Field(default=6, strict=True, ge=1, le=100)
    min_score: float = Field(default=0.12, ge=-1.0, le=1.0, allow_inf_nan=False)
    vector_weight: float = Field(
        default=DEFAULT_VECTOR_WEIGHT,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    keyword_weight: float = Field(
        default=DEFAULT_KEYWORD_WEIGHT,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    reranker_enabled: bool = Field(default=False, strict=True)
    prompt_name: str = Field(default="legal_qa_platform-prompt-v1", min_length=1)
    primary_context_chars: int = Field(default=600, strict=True, ge=1, le=50_000)
    secondary_context_chars: int = Field(default=180, strict=True, ge=1, le=50_000)
    max_context_chars: int = Field(default=1_500, strict=True, ge=1, le=200_000)
    conversation_message_limit: int = Field(default=6, strict=True, ge=0, le=100)
    chat_max_tokens: int = Field(default=1_200, strict=True, ge=1, le=100_000)

    @model_validator(mode="after")
    def validate_baseline_contract(self) -> RagProfile:
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k 不可小於 top_k。")
        if not math.isclose(
            self.vector_weight + self.keyword_weight,
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("vector_weight 與 keyword_weight 的總和必須精確為 1。")
        if self.reranker_enabled:
            raise ValueError("Initial baseline 不允許啟用 reranker。")
        if self.primary_context_chars > self.max_context_chars:
            raise ValueError("primary_context_chars 不可大於 max_context_chars。")
        return self


__all__ = [
    "DEFAULT_KEYWORD_WEIGHT",
    "DEFAULT_VECTOR_WEIGHT",
    "RagProfile",
]
