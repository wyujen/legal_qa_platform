"""Provider-neutral model gateway contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ChatCompletion:
    content: str
    model: str
    request_id: str | None = None
    usage: Mapping[str, int] | None = None


class EmbeddingProvider(Protocol):
    async def embed(
        self,
        texts: Sequence[str],
        *,
        model: str,
        expected_dimension: int,
    ) -> list[list[float]]: ...


class ChatModel(Protocol):
    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        max_tokens: int,
        response_schema: Mapping[str, Any],
    ) -> ChatCompletion: ...
