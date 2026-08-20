"""Small fail-open tracing contract for RAG stages."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Any, Protocol


class Span(Protocol):
    def annotate(
        self,
        *,
        output: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None: ...


class Trace(Span, Protocol):
    @property
    def trace_id(self) -> str | None: ...

    def span(
        self,
        name: str,
        *,
        input: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AbstractContextManager[Span]: ...


class Observability(Protocol):
    def trace(
        self,
        name: str,
        *,
        input: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AbstractContextManager[Trace]: ...
