from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, cast

import pytest
from psycopg import errors as psycopg_errors

from legal_qa_platform.adapters.postgres import PostgresRepository
from legal_qa_platform.ports.repositories import RepositoryReadinessResult


class _Cursor(AbstractAsyncContextManager["_Cursor"]):
    def __init__(
        self,
        row: tuple[object | None] | None,
        error: Exception | None,
    ) -> None:
        self._row = row
        self._error = error

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _query: str) -> None:
        if self._error is not None:
            raise self._error

    async def fetchone(self) -> tuple[object | None] | None:
        return self._row


class _Connection(AbstractAsyncContextManager["_Connection"]):
    def __init__(
        self,
        row: tuple[object | None] | None,
        error: Exception | None,
    ) -> None:
        self._row = row
        self._error = error

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self._row, self._error)


class _Pool:
    def __init__(
        self,
        *,
        row: tuple[object | None] | None = ("legal_qa.legal_provisions",),
        error: Exception | None = None,
    ) -> None:
        self._row = row
        self._error = error

    def connection(self) -> _Connection:
        return _Connection(self._row, self._error)


def _repository(
    *,
    row: tuple[object | None] | None = ("legal_qa.legal_provisions",),
    error: Exception | None = None,
) -> PostgresRepository:
    return PostgresRepository(cast(Any, _Pool(row=row, error=error)))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (("legal_qa.legal_provisions",), "ready"),
        ((None,), "schema_missing"),
        (None, "schema_missing"),
    ],
)
async def test_readiness_distinguishes_ready_from_missing_schema(
    row: tuple[object | None] | None,
    expected: str,
) -> None:
    repository = _repository(row=row)

    result = await repository.readiness_status()

    assert result.category == expected
    assert result.ready is (expected == "ready")
    assert await repository.is_ready() is (expected == "ready")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("PRIVATE_TIMEOUT_MARKER"), "timeout"),
        (
            psycopg_errors.InvalidPassword("PRIVATE_AUTH_MARKER"),
            "authentication_failed",
        ),
        (
            psycopg_errors.InsufficientPrivilege("PRIVATE_PERMISSION_MARKER"),
            "permission_denied",
        ),
        (RuntimeError("PRIVATE_DATABASE_MARKER"), "database_error"),
    ],
)
async def test_readiness_returns_only_allowlisted_redacted_failure_categories(
    error: Exception,
    expected: str,
) -> None:
    repository = _repository(error=error)

    result = await repository.readiness_status()

    assert result.category == expected
    assert result.ready is False
    rendered = repr(result)
    assert "PRIVATE_" not in rendered
    assert str(error) not in rendered


def test_readiness_result_is_immutable() -> None:
    result = RepositoryReadinessResult(category="ready")

    with pytest.raises((AttributeError, TypeError)):
        result.category = "database_error"  # type: ignore[misc]
