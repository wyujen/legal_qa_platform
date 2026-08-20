from __future__ import annotations

from typing import Any

from legal_qa_platform.adapters.observability import LangfuseObservability


class _BrokenClient:
    def start_as_current_observation(self, **_kwargs: Any) -> Any:
        raise RuntimeError("telemetry unavailable")


class _BrokenObservation:
    def update(self, **_kwargs: Any) -> None:
        raise RuntimeError("telemetry update unavailable")


class _BrokenManager:
    def __enter__(self) -> _BrokenObservation:
        return _BrokenObservation()

    def __exit__(self, *_args: Any) -> None:
        raise RuntimeError("telemetry shutdown unavailable")


class _PartiallyBrokenClient:
    def start_as_current_observation(self, **_kwargs: Any) -> _BrokenManager:
        return _BrokenManager()

    def get_current_trace_id(self) -> str:
        raise RuntimeError("trace identity unavailable")


def test_langfuse_start_failure_degrades_to_noop_trace() -> None:
    observability = LangfuseObservability(_BrokenClient())

    with observability.trace("request", metadata={"profile": "baseline"}) as trace:
        assert trace.trace_id is None
        with trace.span("retrieval") as span:
            span.annotate(metadata={"candidate_count": 0})
        trace.annotate(output={"can_answer": False})


def test_langfuse_update_and_shutdown_failures_do_not_escape() -> None:
    observability = LangfuseObservability(_PartiallyBrokenClient())

    with observability.trace("request") as trace:
        assert trace.trace_id is None
        trace.annotate(metadata={"top_k": 6})
        with trace.span("generation") as span:
            span.annotate(error="timeout")
