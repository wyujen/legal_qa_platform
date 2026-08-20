"""Shared secret-safe handling for outbound HTTP failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

from legal_qa_platform.errors import ExternalServiceError

ReadinessCategory = Literal[
    "ready",
    "authentication_failed",
    "authorization_failed",
    "endpoint_not_found",
    "rate_limited",
    "redirect",
    "timeout",
    "connection_error",
    "upstream_error",
    "http_error",
    "invalid_response",
]


@dataclass(frozen=True, slots=True)
class HttpReadinessResult:
    """Allowlisted dependency probe result safe for operator diagnostics."""

    ready: bool
    category: ReadinessCategory
    status_code: int | None = None


def _readiness_status_category(status_code: int) -> ReadinessCategory:
    if 200 <= status_code < 300:
        return "ready"
    if status_code == 401:
        return "authentication_failed"
    if status_code == 403:
        return "authorization_failed"
    if status_code == 404:
        return "endpoint_not_found"
    if status_code in {408, 504}:
        return "timeout"
    if status_code == 429:
        return "rate_limited"
    if 300 <= status_code < 400:
        return "redirect"
    if 500 <= status_code < 600:
        return "upstream_error"
    return "http_error"


async def probe_http_readiness(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout_seconds: float = 2.0,
) -> HttpReadinessResult:
    """Probe one URL while retaining only status/category, never response data."""

    try:
        response = await client.get(url, timeout=timeout_seconds)
    except httpx.TimeoutException:
        return HttpReadinessResult(ready=False, category="timeout")
    except httpx.RequestError:
        return HttpReadinessResult(ready=False, category="connection_error")
    except Exception:
        return HttpReadinessResult(ready=False, category="invalid_response")

    category = _readiness_status_category(response.status_code)
    return HttpReadinessResult(
        ready=category == "ready",
        category=category,
        status_code=response.status_code,
    )


def external_http_error(service: str, exc: Exception) -> ExternalServiceError:
    """Classify an HTTP failure without retaining URL, headers, or body."""

    if isinstance(exc, httpx.TimeoutException):
        return ExternalServiceError(service, "timeout")
    if isinstance(exc, httpx.HTTPStatusError):
        return ExternalServiceError(
            service,
            "http_error",
            f"status={exc.response.status_code}",
        )
    if isinstance(exc, httpx.RequestError):
        return ExternalServiceError(service, "connection_error")
    return ExternalServiceError(service, "invalid_response")


def require_success(service: str, response: httpx.Response) -> None:
    """Raise a redacted error; never include response content or request headers."""

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise external_http_error(service, exc) from None
