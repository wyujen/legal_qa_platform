from __future__ import annotations

import logging

import pytest
from pydantic import SecretStr

from legal_qa_platform.adapters.postgres import (
    _safe_database_error,
    create_postgres_pool,
)
from legal_qa_platform.config import RuntimeSettings


@pytest.mark.asyncio
async def test_pool_diagnostics_cannot_reach_application_log_handlers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = RuntimeSettings.model_construct(
        postgres_external_host="postgres.example.invalid",
        postgres_internal_host=None,
        postgres_port=5432,
        postgres_user="application-user",
        postgres_password=SecretStr("unit-test-password"),
        postgres_database="application-database",
        qdrant_public_url=None,
        qdrant_internal_http_url=None,
        qdrant_internal_grpc_endpoint=None,
        qdrant_api_key=None,
        litellm_public_url=None,
        litellm_internal_url=None,
        litellm_api_key=None,
    )
    pool = create_postgres_pool(settings, min_size=0, max_size=1)
    private_marker = "private-host-or-dsn-marker"

    try:
        with caplog.at_level(logging.WARNING):
            logging.getLogger("psycopg.pool").warning(
                "error connecting in %r: %s",
                "legal_qa_platform",
                RuntimeError(private_marker),
            )
            logging.getLogger("legal_qa_platform.test").warning(
                "postgresql readiness failed"
            )
    finally:
        await pool.close()

    assert private_marker not in caplog.text
    assert "error connecting" not in caplog.text
    assert "postgresql readiness failed" in caplog.text


@pytest.mark.parametrize(
    ("exception_type", "expected_category"),
    [
        (TimeoutError, "timeout"),
        (PermissionError, "permission_denied"),
        (type("AuthenticationFailure", (Exception,), {}), "authentication_failed"),
        (RuntimeError, "database_error"),
    ],
)
def test_database_failures_keep_safe_categories_without_exception_text(
    exception_type: type[Exception],
    expected_category: str,
) -> None:
    private_marker = "private-postgresql-exception-marker"

    error = _safe_database_error(exception_type(private_marker))

    assert error.service == "postgresql"
    assert error.category == expected_category
    assert private_marker not in str(error)
