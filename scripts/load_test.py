"""Bounded REST load test with application and gateway/model signal separation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Literal, cast
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from legal_qa_platform import __version__
from legal_qa_platform.api.schemas import HealthResponse, RetrieveResponse
from legal_qa_platform.async_runtime import run_async
from legal_qa_platform.domain.qa import ChatResponse
from legal_qa_platform.services.data_loader import load_question_bank
from legal_qa_platform.services.profile_loader import load_profile

try:
    from scripts._cli import (
        PROJECT_ROOT,
        latency_summary,
        repository_output_path,
        repository_path,
        utc_run_stamp,
        write_json,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from _cli import (  # type: ignore[import-not-found, no-redef]
        PROJECT_ROOT,
        latency_summary,
        repository_output_path,
        repository_path,
        utc_run_stamp,
        write_json,
    )

DEFAULT_CONCURRENCY = (1, 5, 10, 20, 50, 100)
DEFAULT_QUESTIONS_PATH = PROJECT_ROOT / "data" / "qa_test_questions.json"
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "profiles" / "platform-baseline-v1.json"
_SAFE_ERROR_CATEGORIES = frozenset(
    {
        "authentication_failed",
        "configuration",
        "connection_error",
        "database_error",
        "http_error",
        "invalid_response",
        "permission_denied",
        "quota_exceeded",
        "rate_limited",
        "response_validation",
        "timeout",
    }
)
_STAGE_ALLOWLIST = frozenset(
    {
        "normalize",
        "conversation_context",
        "embedding",
        "vector_retrieval",
        "keyword_retrieval",
        "hybrid_ranking",
        "context_build",
        "generation",
        "response_validation",
        "citation_validation",
        "total",
    }
)
_HTTP_SCHEME = re.compile(r"^https?$")


@dataclass(frozen=True, slots=True)
class RequestSample:
    status_code: int | None
    duration_ms: float
    success: bool
    timeout: bool
    error_category: str | None
    stage_latencies_ms: dict[str, float]
    structured_valid: bool | None
    citation_allowlist_valid: bool | None
    answer_nonempty: bool | None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_concurrency(value: str) -> tuple[int, ...]:
    try:
        levels = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "concurrency must be comma-separated integers"
        ) from exc
    if not levels or any(level <= 0 or level > 1_000 for level in levels):
        raise argparse.ArgumentTypeError(
            "concurrency levels must be between 1 and 1000"
        )
    if tuple(sorted(set(levels))) != levels:
        raise argparse.ArgumentTypeError(
            "concurrency levels must be unique and strictly increasing"
        )
    return levels


def validate_api_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
        username = parsed.username
        password = parsed.password
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "API base URL must be plain HTTP(S) without credentials, query, or fragment"
        ) from exc
    if (
        not _HTTP_SCHEME.fullmatch(parsed.scheme)
        or not hostname
        or username is not None
        or password is not None
        or (port is not None and not 1 <= port <= 65_535)
        or parsed.query
        or parsed.fragment
    ):
        raise argparse.ArgumentTypeError(
            "API base URL must be plain HTTP(S) without credentials, query, or fragment"
        )
    return value.rstrip("/")


def _allowlisted_stages(raw: object) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    output: dict[str, float] = {}
    for name, value in raw.items():
        if (
            name in _STAGE_ALLOWLIST
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) >= 0
        ):
            output[str(name)] = float(value)
    return output


def _error_category(response: httpx.Response) -> str:
    if response.status_code == 429:
        return "rate_limited"
    try:
        payload = response.json()
    except ValueError:
        return f"http_{response.status_code}"
    category = payload.get("category") if isinstance(payload, dict) else None
    if isinstance(category, str) and category in _SAFE_ERROR_CATEGORIES:
        return category
    return f"http_{response.status_code}"


async def request_once(
    client: httpx.AsyncClient,
    *,
    scenario: Literal["health", "retrieve", "chat"],
    question: str,
    profile_name: str,
) -> RequestSample:
    started = perf_counter()
    try:
        if scenario == "health":
            response = await client.get("/health")
        elif scenario == "retrieve":
            response = await client.post(
                "/api/v1/retrieve",
                json={"message": question, "profile": profile_name},
            )
        else:
            response = await client.post(
                "/api/v1/chat",
                json={"message": question, "profile": profile_name},
            )
    except httpx.TimeoutException:
        return RequestSample(
            status_code=None,
            duration_ms=(perf_counter() - started) * 1_000,
            success=False,
            timeout=True,
            error_category="timeout",
            stage_latencies_ms={},
            structured_valid=None,
            citation_allowlist_valid=None,
            answer_nonempty=None,
        )
    except httpx.RequestError:
        return RequestSample(
            status_code=None,
            duration_ms=(perf_counter() - started) * 1_000,
            success=False,
            timeout=False,
            error_category="connection_error",
            stage_latencies_ms={},
            structured_valid=None,
            citation_allowlist_valid=None,
            answer_nonempty=None,
        )

    duration_ms = (perf_counter() - started) * 1_000
    if response.status_code >= 400:
        return RequestSample(
            status_code=response.status_code,
            duration_ms=duration_ms,
            success=False,
            timeout=False,
            error_category=_error_category(response),
            stage_latencies_ms={},
            structured_valid=None,
            citation_allowlist_valid=None,
            answer_nonempty=None,
        )

    try:
        payload = response.json()
        if scenario == "health":
            HealthResponse.model_validate(payload)
            stages: dict[str, float] = {}
            structured: bool | None = None
            citation_valid: bool | None = None
            answer_nonempty: bool | None = None
        elif scenario == "retrieve":
            parsed_retrieval = RetrieveResponse.model_validate(payload)
            stages = _allowlisted_stages(parsed_retrieval.stage_latencies_ms)
            structured = True
            citation_valid = None
            answer_nonempty = None
        else:
            parsed_chat = ChatResponse.model_validate(payload)
            stages = _allowlisted_stages(parsed_chat.stage_latencies_ms)
            structured = parsed_chat.response is not None and parsed_chat.error is None
            if parsed_chat.response is None:
                citation_valid = False
                answer_nonempty = False
            else:
                retrieved_ids = {
                    result.provision_id for result in parsed_chat.retrieval_results
                }
                citation_valid = {
                    item.provision_id for item in parsed_chat.response.citations
                }.issubset(retrieved_ids)
                answer_nonempty = bool(parsed_chat.response.summary.strip())
    except (ValueError, ValidationError):
        return RequestSample(
            status_code=response.status_code,
            duration_ms=duration_ms,
            success=False,
            timeout=False,
            error_category="response_validation",
            stage_latencies_ms={},
            structured_valid=False,
            citation_allowlist_valid=False if scenario == "chat" else None,
            answer_nonempty=False if scenario == "chat" else None,
        )

    return RequestSample(
        status_code=response.status_code,
        duration_ms=duration_ms,
        success=True,
        timeout=False,
        error_category=None,
        stage_latencies_ms=stages,
        structured_valid=structured,
        citation_allowlist_valid=citation_valid,
        answer_nonempty=answer_nonempty,
    )


def summarize_level(
    samples: Sequence[RequestSample],
    *,
    concurrency: int,
    wall_seconds: float,
) -> dict[str, object]:
    if not samples or wall_seconds <= 0:
        raise ValueError("samples and positive wall time are required")
    successes = sum(item.success for item in samples)
    status_counts = Counter(
        str(item.status_code) if item.status_code is not None else "transport"
        for item in samples
    )
    errors = Counter(
        item.error_category for item in samples if item.error_category is not None
    )
    stage_samples: dict[str, list[float]] = defaultdict(list)
    for item in samples:
        for name, duration in item.stage_latencies_ms.items():
            if name in _STAGE_ALLOWLIST:
                stage_samples[name].append(duration)

    generation = stage_samples.get("generation", [])
    total = stage_samples.get("total", [])
    generation_share = (
        sum(generation) / sum(total)
        if generation and total and sum(total) > 0
        else None
    )
    gateway_quota_count = sum(
        item.status_code == 429
        or item.error_category in {"rate_limited", "quota_exceeded"}
        for item in samples
    )
    application_5xx_count = sum(
        count
        for status_code, count in status_counts.items()
        if status_code.isdigit() and 500 <= int(status_code) <= 599
    )
    if gateway_quota_count:
        attribution = "gateway_quota_signal"
    elif generation_share is not None and generation_share >= 0.70:
        attribution = "gateway_or_model_latency_dominant"
    elif application_5xx_count or errors.get("connection_error", 0):
        attribution = "application_or_dependency_signal"
    else:
        attribution = "no_clear_capacity_signal"

    structured_values = [
        item.structured_valid for item in samples if item.structured_valid is not None
    ]
    citation_values = [
        item.citation_allowlist_valid
        for item in samples
        if item.citation_allowlist_valid is not None
    ]
    answer_values = [
        item.answer_nonempty for item in samples if item.answer_nonempty is not None
    ]
    return {
        "concurrency": concurrency,
        "request_count": len(samples),
        "success_count": successes,
        "wall_seconds": wall_seconds,
        "requests_per_second": len(samples) / wall_seconds,
        "successful_requests_per_second": successes / wall_seconds,
        "error_rate": (len(samples) - successes) / len(samples),
        "timeout_rate": sum(item.timeout for item in samples) / len(samples),
        "http_status_counts": dict(sorted(status_counts.items())),
        "error_categories": dict(sorted(errors.items())),
        "latency_ms": latency_summary([item.duration_ms for item in samples]),
        "stage_latency_ms": {
            name: latency_summary(values)
            for name, values in sorted(stage_samples.items())
        },
        "correctness": {
            "structured_validation_pass_rate": (
                sum(structured_values) / len(structured_values)
                if structured_values
                else None
            ),
            "citation_allowlist_pass_rate": (
                sum(citation_values) / len(citation_values) if citation_values else None
            ),
            "nonempty_answer_rate": (
                sum(answer_values) / len(answer_values) if answer_values else None
            ),
        },
        "capacity_signals": {
            "gateway_quota_signal_count": gateway_quota_count,
            "possible_litellm_gateway_quota_signal_count": gateway_quota_count,
            "generation_share_of_reported_total": generation_share,
            "application_or_dependency_5xx_count": application_5xx_count,
            "transport_connection_error_count": errors.get("connection_error", 0),
            "attribution": attribution,
            "attribution_is_diagnostic_not_a_capacity_limit": True,
        },
    }


async def _preflight(client: httpx.AsyncClient) -> bool:
    for path, label in (("/health", "health"), ("/ready", "readiness")):
        try:
            response = await client.get(path)
        except httpx.HTTPError:
            print(f"[FAIL] API {label} category=transport")
            return False
        if response.status_code >= 400:
            print(f"[FAIL] API {label} status={response.status_code}")
            return False
        print(f"[PASS] API {label} status={response.status_code}")
    return True


async def _run_level(
    client: httpx.AsyncClient,
    *,
    scenario: Literal["health", "retrieve", "chat"],
    questions: Sequence[str],
    profile_name: str,
    concurrency: int,
    request_count: int,
) -> tuple[list[RequestSample], float]:
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(index: int) -> RequestSample:
        async with semaphore:
            return await request_once(
                client,
                scenario=scenario,
                question=questions[index % len(questions)],
                profile_name=profile_name,
            )

    started = perf_counter()
    samples = await asyncio.gather(*(bounded(index) for index in range(request_count)))
    return list(samples), perf_counter() - started


async def run_load_test(
    *,
    api_base_url: str,
    scenario: Literal["health", "retrieve", "chat"],
    questions: Sequence[str],
    profile_name: str,
    concurrency_levels: Sequence[int],
    requests_per_level: int,
    warmup_requests: int,
    timeout_seconds: float,
    stop_error_rate: float | None,
    stop_on_gateway_quota: bool,
) -> tuple[list[dict[str, object]], str | None]:
    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(base_url=api_base_url, timeout=timeout) as client:
        if not await _preflight(client):
            return [], "preflight_failed"
        for index in range(warmup_requests):
            await request_once(
                client,
                scenario=scenario,
                question=questions[index % len(questions)],
                profile_name=profile_name,
            )

        levels: list[dict[str, object]] = []
        stopped_reason: str | None = None
        for concurrency in concurrency_levels:
            samples, wall_seconds = await _run_level(
                client,
                scenario=scenario,
                questions=questions,
                profile_name=profile_name,
                concurrency=concurrency,
                request_count=requests_per_level,
            )
            summary = summarize_level(
                samples,
                concurrency=concurrency,
                wall_seconds=wall_seconds,
            )
            levels.append(summary)
            print(
                f"[RUN] load concurrency={concurrency} requests={requests_per_level} "
                f"success={summary['success_count']}"
            )
            signals = cast(dict[str, object], summary["capacity_signals"])
            if (
                stop_on_gateway_quota
                and int(cast(int, signals["gateway_quota_signal_count"])) > 0
            ):
                stopped_reason = "gateway_quota_signal"
            elif (
                stop_error_rate is not None
                and float(cast(float, summary["error_rate"])) >= stop_error_rate
            ):
                stopped_reason = "error_rate_threshold"
            if stopped_reason is not None:
                print(f"[STOP] load escalation reason={stopped_reason}")
                break
    return levels, stopped_reason


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run bounded, escalating REST load scenarios."
    )
    parser.add_argument(
        "--api-base-url",
        type=validate_api_base_url,
        default="http://127.0.0.1:8000",
        help="Credential-free API base URL; it is never written to the report.",
    )
    parser.add_argument(
        "--scenario", choices=("health", "retrieve", "chat"), default="chat"
    )
    parser.add_argument(
        "--concurrency",
        type=parse_concurrency,
        default=DEFAULT_CONCURRENCY,
        help="Ascending levels (default: 1,5,10,20,50,100).",
    )
    parser.add_argument("--requests-per-level", type=int, default=100)
    parser.add_argument("--warmup-requests", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument(
        "--stop-error-rate",
        type=float,
        default=None,
        help="Optional early-stop threshold; omitted by default so all levels run.",
    )
    parser.add_argument(
        "--stop-on-gateway-quota",
        action="store_true",
        help="Opt in to stopping after an explicit gateway quota signal.",
    )
    parser.add_argument("--questions", default="data/qa_test_questions.json")
    parser.add_argument("--profile", default="profiles/platform-baseline-v1.json")
    parser.add_argument(
        "--output",
        default=None,
        help="Repository-relative report path under test-results by default.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    levels = cast(tuple[int, ...], args.concurrency)
    if args.requests_per_level < max(levels):
        print("[FAIL] --requests-per-level must cover the largest concurrency level.")
        return 2
    if args.warmup_requests < 0 or args.timeout_seconds <= 0:
        print("[FAIL] warmup must be non-negative and timeout must be positive.")
        return 2
    if args.stop_error_rate is not None and not 0.0 < args.stop_error_rate <= 1.0:
        print("[FAIL] --stop-error-rate must be greater than 0 and at most 1.")
        return 2
    default_output = PROJECT_ROOT / "test-results" / f"load-{utc_run_stamp()}.json"
    try:
        questions_path = repository_path(args.questions, default=DEFAULT_QUESTIONS_PATH)
        profile_path = repository_path(args.profile, default=DEFAULT_PROFILE_PATH)
        output_path = repository_output_path(args.output, default=default_output)
        questions = load_question_bank(questions_path)
        profile = load_profile(profile_path)
    except Exception as exc:
        print(f"[FAIL] load-test setup category={type(exc).__name__}")
        return 2

    scenario = cast(Literal["health", "retrieve", "chat"], args.scenario)
    try:
        result_levels, stopped_reason = run_async(
            run_load_test(
                api_base_url=args.api_base_url,
                scenario=scenario,
                questions=[item.question for item in questions],
                profile_name=profile.name,
                concurrency_levels=levels,
                requests_per_level=args.requests_per_level,
                warmup_requests=args.warmup_requests,
                timeout_seconds=args.timeout_seconds,
                stop_error_rate=args.stop_error_rate,
                stop_on_gateway_quota=args.stop_on_gateway_quota,
            )
        )
    except Exception as exc:
        print(f"[FAIL] load-test runtime category={type(exc).__name__}")
        return 1
    safe_configuration = {
        "scenario": scenario,
        "profile_name": profile.name,
        "prompt_name": profile.prompt_name,
        "chat_model": profile.chat_model,
        "embedding_model": profile.embedding_model,
        "top_k": profile.top_k,
        "concurrency_levels": list(levels),
        "requests_per_level": args.requests_per_level,
        "warmup_requests": args.warmup_requests,
    }
    report = {
        "schema_version": 1,
        "created_at_utc": utc_run_stamp(),
        "application_version": __version__,
        "target": "operator-supplied-api",
        "scenario": scenario,
        "configuration_fingerprint": _fingerprint(safe_configuration),
        "dataset": {
            "question_count": len(questions),
            "questions_sha256": _sha256_file(questions_path),
        },
        "profile": {
            "name": profile.name,
            "profile_sha256": _sha256_file(profile_path),
            "prompt_name": profile.prompt_name,
            "chat_model": profile.chat_model,
            "embedding_model": profile.embedding_model,
            "top_k": profile.top_k,
        },
        "requested_concurrency_levels": list(levels),
        "requests_per_level": args.requests_per_level,
        "warmup_requests": args.warmup_requests,
        "early_stop": {
            "error_rate_threshold": args.stop_error_rate,
            "stop_on_gateway_quota": args.stop_on_gateway_quota,
        },
        "stopped_reason": stopped_reason,
        "levels": result_levels,
        "interpretation": {
            "application_capacity_and_gateway_model_capacity_are_separate": True,
            "gateway_quota_values_are_operator_managed": True,
            "http_signals_alone_do_not_prove_litellm_attribution": True,
            "results_do_not_set_a_production_limit": True,
        },
    }
    try:
        write_json(output_path, report)
    except Exception as exc:
        print(f"[FAIL] load report category={type(exc).__name__}")
        return 1
    relative_output = output_path.relative_to(PROJECT_ROOT).as_posix()
    if not result_levels:
        print(
            f"[FAIL] load test did not complete reason={stopped_reason} "
            f"report={relative_output}"
        )
        return 1
    if stopped_reason is not None or len(result_levels) != len(levels):
        print(
            f"[FAIL] load test stopped reason={stopped_reason} "
            f"completed_levels={len(result_levels)}/{len(levels)} "
            f"report={relative_output}"
        )
        return 1
    print(f"[PASS] load test levels={len(result_levels)} report={relative_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
