"""Shared secret-safe handling for outbound HTTP failures."""

from __future__ import annotations

import httpx

from legal_qa_platform.errors import ExternalServiceError


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
