from __future__ import annotations

import socket
import ssl
from collections.abc import Callable

import httpx
import pytest

from legal_qa_platform.adapters.http_safety import (
    external_http_error,
    probe_http_readiness,
)


def _wrapped_connect_error(cause: Exception) -> httpx.ConnectError:
    request = httpx.Request("GET", "https://private-endpoint.example.invalid")
    try:
        raise cause
    except Exception as inner:
        try:
            raise httpx.ConnectError(
                "PRIVATE_TRANSPORT_MARKER",
                request=request,
            ) from inner
        except httpx.ConnectError as outer:
            return outer


def _tls_error() -> httpx.RequestError:
    return _wrapped_connect_error(ssl.SSLCertVerificationError(1, "PRIVATE_TLS_MARKER"))


def _dns_error() -> httpx.RequestError:
    return _wrapped_connect_error(socket.gaierror(-2, "PRIVATE_DNS_MARKER"))


def _connection_error() -> httpx.RequestError:
    return httpx.ConnectError(
        "PRIVATE_CONNECTION_MARKER",
        request=httpx.Request("GET", "https://private-endpoint.example.invalid"),
    )


def _timeout_error() -> httpx.RequestError:
    return httpx.ConnectTimeout(
        "PRIVATE_TIMEOUT_MARKER",
        request=httpx.Request("GET", "https://private-endpoint.example.invalid"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_factory", "expected_category"),
    [
        (_tls_error, "tls_error"),
        (_dns_error, "dns_error"),
        (_connection_error, "connection_error"),
        (_timeout_error, "timeout"),
    ],
)
async def test_transport_category_is_shared_and_secret_safe(
    error_factory: Callable[[], httpx.RequestError],
    expected_category: str,
) -> None:
    class FailedClient:
        async def get(self, _url: str, **_kwargs: float) -> httpx.Response:
            raise error_factory()

    readiness = await probe_http_readiness(  # type: ignore[arg-type]
        FailedClient(),
        "https://private-endpoint.example.invalid",
    )
    external_error = external_http_error("dependency", error_factory())

    assert readiness.category == expected_category
    assert readiness.status_code is None
    assert external_error.category == expected_category
    safe_output = f"{readiness!r} {external_error!s}"
    assert "PRIVATE_" not in safe_output
    assert "private-endpoint" not in safe_output


def test_nested_timeout_is_classified_by_type_without_message_inspection() -> None:
    error = _wrapped_connect_error(TimeoutError("PRIVATE_TIMEOUT_CAUSE_MARKER"))

    classified = external_http_error("dependency", error)

    assert classified.category == "timeout"
    assert "PRIVATE_TIMEOUT_CAUSE_MARKER" not in str(classified)
