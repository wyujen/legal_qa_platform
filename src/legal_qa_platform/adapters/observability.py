"""No-op and injected Langfuse observability implementations."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Any, Literal

logger = logging.getLogger(__name__)


class _NoopSpan:
    def annotate(
        self,
        *,
        output: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        del output, metadata, error


class _NoopTrace(_NoopSpan):
    @property
    def trace_id(self) -> str | None:
        return None

    def span(
        self,
        name: str,
        *,
        input: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AbstractContextManager[_NoopSpan]:
        del name, input, metadata
        return _NoopContext(_NoopSpan())


class _NoopContext(AbstractContextManager[Any]):
    def __init__(self, value: Any) -> None:
        self._value = value

    def __enter__(self) -> Any:
        return self._value

    def __exit__(self, *_: object) -> Literal[False]:
        return False


class NoopObservability:
    """Default when the documented runtime contract has no Langfuse settings."""

    def trace(
        self,
        name: str,
        *,
        input: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AbstractContextManager[_NoopTrace]:
        del name, input, metadata
        return _NoopContext(_NoopTrace())


class _LangfuseSpan(_NoopSpan):
    def __init__(self, observation: Any) -> None:
        self._observation = observation

    def annotate(
        self,
        *,
        output: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        values: dict[str, Any] = {}
        if output is not None:
            values["output"] = output
        if metadata:
            values["metadata"] = dict(metadata)
        if error:
            values.update(level="ERROR", status_message=error)
        try:
            if values:
                self._observation.update(**values)
        except Exception:
            logger.warning("Langfuse span update failed", exc_info=False)


class _LangfuseTrace(_LangfuseSpan):
    def __init__(self, client: Any, observation: Any) -> None:
        super().__init__(observation)
        self._client = client

    @property
    def trace_id(self) -> str | None:
        try:
            value = self._client.get_current_trace_id()
            return value if isinstance(value, str) else None
        except Exception:
            return None

    def span(
        self,
        name: str,
        *,
        input: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AbstractContextManager[_NoopSpan]:
        return _LangfuseContext(
            self._client,
            name=name,
            input=input,
            metadata=metadata,
            trace=False,
        )


class _LangfuseContext(AbstractContextManager[Any]):
    """Convert every SDK/configuration failure into a no-op span."""

    def __init__(
        self,
        client: Any,
        *,
        name: str,
        input: Any | None,
        metadata: Mapping[str, Any] | None,
        trace: bool,
    ) -> None:
        self._client = client
        self._name = name
        self._input = input
        self._metadata = metadata
        self._trace = trace
        self._manager: Any | None = None
        self._span: _NoopSpan = _NoopSpan()

    def __enter__(self) -> Any:
        try:
            self._manager = self._client.start_as_current_observation(
                name=self._name,
                as_type="span",
                input=self._input,
                metadata=dict(self._metadata or {}),
            )
            observation = self._manager.__enter__()
            if self._trace:
                self._span = _LangfuseTrace(self._client, observation)
            else:
                self._span = _LangfuseSpan(observation)
        except Exception:
            logger.warning("Langfuse span start failed; continuing", exc_info=False)
            self._manager = None
            self._span = _NoopTrace() if self._trace else _NoopSpan()
        return self._span

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> Literal[False]:
        if exc is not None:
            self._span.annotate(error=type(exc).__name__)
        if self._manager is not None:
            try:
                self._manager.__exit__(exc_type, exc, traceback)
            except Exception:
                logger.warning("Langfuse span end failed; continuing", exc_info=False)
        return False


class LangfuseObservability:
    """Fail-open adapter around an already configured Langfuse v4 client.

    Client construction is intentionally outside this repository's default
    composition because the approved environment-variable contract currently
    contains no Langfuse credential names.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def trace(
        self,
        name: str,
        *,
        input: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AbstractContextManager[Any]:
        return _LangfuseContext(
            self._client,
            name=name,
            input=input,
            metadata=metadata,
            trace=True,
        )
