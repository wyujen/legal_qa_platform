from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, cast

import pytest

from legal_qa_platform.adapters.postgres import (
    PostgresMigrationRunner,
    _admin_connection_config,
    _runtime_grant_statements,
    _validate_migration_preflight,
)
from legal_qa_platform.config import PostgresMigrationSettings
from legal_qa_platform.config.settings import DOCUMENTED_ENVIRONMENT_VARIABLES
from legal_qa_platform.errors import ExternalServiceError
from scripts import migrate

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parents[2] / "migrations"


def _admin_settings() -> PostgresMigrationSettings:
    return PostgresMigrationSettings.model_validate(
        {
            "POSTGRES_EXTERNAL_HOST": "postgres.example.invalid",
            "POSTGRES_PORT": 5432,
            "POSTGRES_ADMIN_USER": "migration-owner",
            "POSTGRES_ADMIN_PASSWORD": "unit-test-admin-password",
            "POSTGRES_ADMIN_DATABASE": "application-database",
            "POSTGRES_LITELLM_USER": "application-role",
            "POSTGRES_LITELLM_DATABASE": "application-database",
        }
    )


def test_admin_connection_targets_application_database_with_admin_identity() -> None:
    config = _admin_connection_config(_admin_settings())

    assert config.host == "postgres.example.invalid"
    assert config.port == 5432
    assert config.user == "migration-owner"
    assert config.database == "application-database"
    assert str(config.password) == "**********"
    assert "unit-test-admin-password" not in repr(config)


@pytest.mark.parametrize(
    ("row", "category"),
    [
        (None, "target_database_mismatch"),
        ((False, True, True, False), "target_database_mismatch"),
        ((True, False, False, False), "runtime_role_missing"),
        ((True, True, False, False), "runtime_role_login_disabled"),
        ((True, True, True, True), "runtime_role_overprivileged"),
    ],
)
def test_migration_preflight_rejects_unsafe_state_without_details(
    row: tuple[bool, bool, bool, bool] | None,
    category: str,
) -> None:
    with pytest.raises(ExternalServiceError) as caught:
        _validate_migration_preflight(row)

    assert caught.value.category == category
    assert "application-role" not in str(caught.value)


def test_migration_preflight_accepts_existing_low_privilege_login_role() -> None:
    _validate_migration_preflight((True, True, True, False))


def test_runtime_grants_are_identifier_safe_and_schema_scoped() -> None:
    rendered = [
        statement.as_string()
        for statement in _runtime_grant_statements(
            target_database="application-database",
            application_role="application-role",
        )
    ]

    assert rendered == [
        'GRANT CONNECT ON DATABASE "application-database" TO "application-role"',
        'GRANT USAGE ON SCHEMA legal_qa TO "application-role"',
        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA legal_qa FROM "
        '"application-role"',
        "REVOKE ALL PRIVILEGES ON TABLE legal_qa.schema_migrations FROM "
        '"application-role"',
        "GRANT SELECT, INSERT, UPDATE ON TABLE legal_qa.collection_runs, "
        "legal_qa.legal_documents, legal_qa.provision_identity_ledger, "
        "legal_qa.legal_provisions, legal_qa.conversations, legal_qa.qa_runs TO "
        '"application-role"',
        "GRANT SELECT, INSERT ON TABLE legal_qa.legal_provision_versions, "
        "legal_qa.collection_run_items, legal_qa.messages, "
        "legal_qa.qa_retrievals, legal_qa.feedback TO "
        '"application-role"',
        "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA legal_qa FROM "
        '"application-role"',
        'GRANT USAGE ON ALL SEQUENCES IN SCHEMA legal_qa TO "application-role"',
    ]
    assert all("legal_qa" in item or "CONNECT ON DATABASE" in item for item in rendered)
    assert not any("CREATE ROLE" in item or "ALTER ROLE" in item for item in rendered)
    grants = [item for item in rendered if item.startswith("GRANT")]
    assert not any("schema_migrations" in item for item in grants)
    assert not any("DELETE" in item for item in grants)
    assert not any("ALTER DEFAULT PRIVILEGES" in item for item in rendered)
    assert not any("UPDATE ON ALL SEQUENCES" in item for item in rendered)


class _Cursor(AbstractAsyncContextManager["_Cursor"]):
    def __init__(
        self,
        *,
        preflight: tuple[bool, bool, bool, bool],
        applied: tuple[str, ...] = (),
    ) -> None:
        self.preflight = preflight
        self.applied = applied
        self.executed: list[str] = []

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(
        self,
        query: Any,
        _params: object = None,
        *,
        prepare: bool | None = None,
    ) -> None:
        del prepare
        rendered = query if isinstance(query, str) else query.as_string()
        self.executed.append(" ".join(rendered.split()))

    async def fetchone(self) -> tuple[bool, bool, bool, bool]:
        return self.preflight

    async def fetchall(self) -> list[tuple[str]]:
        return [(version,) for version in self.applied]


class _Transaction(AbstractAsyncContextManager["_Transaction"]):
    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Connection(AbstractAsyncContextManager["_Connection"]):
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def transaction(self) -> _Transaction:
        return _Transaction()

    def cursor(self) -> _Cursor:
        return self._cursor


class _Pool:
    def __init__(self, cursor: _Cursor) -> None:
        self._connection = _Connection(cursor)

    def connection(self) -> _Connection:
        return self._connection


def _runner(cursor: _Cursor) -> PostgresMigrationRunner:
    return PostgresMigrationRunner(
        cast(Any, _Pool(cursor)),
        application_role="application-role",
        target_database="application-database",
    )


@pytest.mark.asyncio
async def test_runner_preflights_before_ddl_then_grants_runtime_access() -> None:
    cursor = _Cursor(preflight=(True, True, True, False))

    applied = await _runner(cursor).apply_migrations(MIGRATIONS_DIRECTORY)

    assert applied == ("0001_initial.sql",)
    preflight_index = next(
        index for index, query in enumerate(cursor.executed) if "FROM pg_roles" in query
    )
    ddl_index = cursor.executed.index("CREATE SCHEMA IF NOT EXISTS legal_qa")
    grant_index = next(
        index
        for index, query in enumerate(cursor.executed)
        if query.startswith("GRANT CONNECT")
    )
    assert preflight_index < ddl_index < grant_index
    assert any("legal_qa.collection_runs" in query for query in cursor.executed)


@pytest.mark.asyncio
async def test_runner_does_not_execute_ddl_when_runtime_role_is_missing() -> None:
    cursor = _Cursor(preflight=(True, False, False, False))

    with pytest.raises(ExternalServiceError) as caught:
        await _runner(cursor).apply_migrations(MIGRATIONS_DIRECTORY)

    assert caught.value.category == "runtime_role_missing"
    assert len(cursor.executed) == 1
    assert "FROM pg_roles" in cursor.executed[0]


def test_migration_cli_requires_admin_identity_but_not_runtime_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in DOCUMENTED_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    values = {
        "POSTGRES_EXTERNAL_HOST": "public-postgres.example.invalid",
        "POSTGRES_INTERNAL_HOST": "internal-postgres.example.invalid",
        "POSTGRES_PORT": "5432",
        "POSTGRES_ADMIN_USER": "migration-owner",
        "POSTGRES_ADMIN_PASSWORD": "PRIVATE_ADMIN_PASSWORD_MARKER",
        "POSTGRES_ADMIN_DATABASE": "application-database",
        "POSTGRES_LITELLM_USER": "application-role",
        "POSTGRES_LITELLM_DATABASE": "application-database",
        "POSTGRES_LITELLM_PASSWORD": "PRIVATE_RUNTIME_PASSWORD_MARKER",
        "QDRANT_API_KEY": "PRIVATE_QDRANT_KEY_MARKER",
        "LITELLM_API_KEY": "PRIVATE_LITELLM_KEY_MARKER",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    invoked = False

    def fake_run_async(coroutine: Any) -> int:
        nonlocal invoked
        invoked = True
        coroutine.close()
        return 0

    monkeypatch.setattr(migrate, "run_async", fake_run_async)

    exit_code = migrate.main(["--endpoint-scope", "public"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert invoked is True
    assert "scope=public postgres=external" in output
    assert "POSTGRES_LITELLM_PASSWORD" not in output
    assert "PRIVATE_ADMIN_PASSWORD_MARKER" not in output
    assert "PRIVATE_RUNTIME_PASSWORD_MARKER" not in output
    assert "PRIVATE_QDRANT_KEY_MARKER" not in output
    assert "PRIVATE_LITELLM_KEY_MARKER" not in output
