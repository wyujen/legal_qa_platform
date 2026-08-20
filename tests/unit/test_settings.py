from __future__ import annotations

import pytest

from legal_qa_platform.config.settings import (
    DOCUMENTED_ENVIRONMENT_VARIABLES,
    POSTGRES_MIGRATION_ENVIRONMENT_VARIABLES,
    RUNTIME_ENVIRONMENT_VARIABLES,
    PostgresMigrationSettings,
    RuntimeSettings,
)
from legal_qa_platform.errors import ConfigurationError


def make_runtime_settings(**updates: object) -> RuntimeSettings:
    """Construct runtime settings from explicit inputs, never process env."""

    values: dict[str, object] = {name: None for name in RUNTIME_ENVIRONMENT_VARIABLES}
    values.update(updates)
    return RuntimeSettings.model_validate(values)


def make_migration_settings(**updates: object) -> PostgresMigrationSettings:
    """Construct migration settings from explicit inputs, never process env."""

    values: dict[str, object] = {
        name: None for name in POSTGRES_MIGRATION_ENVIRONMENT_VARIABLES
    }
    values.update(updates)
    return PostgresMigrationSettings.model_validate(values)


def test_environment_contract_is_split_without_widening_documented_allowlist() -> None:
    documented = (
        "POSTGRES_EXTERNAL_HOST",
        "POSTGRES_INTERNAL_HOST",
        "POSTGRES_PORT",
        "POSTGRES_ADMIN_USER",
        "POSTGRES_ADMIN_PASSWORD",
        "POSTGRES_ADMIN_DATABASE",
        "POSTGRES_LITELLM_USER",
        "POSTGRES_LITELLM_PASSWORD",
        "POSTGRES_LITELLM_DATABASE",
        "QDRANT_PUBLIC_URL",
        "QDRANT_INTERNAL_HTTP_URL",
        "QDRANT_INTERNAL_GRPC_ENDPOINT",
        "QDRANT_API_KEY",
        "LITELLM_PUBLIC_URL",
        "LITELLM_INTERNAL_URL",
        "LITELLM_API_KEY",
    )
    runtime = (
        "POSTGRES_EXTERNAL_HOST",
        "POSTGRES_INTERNAL_HOST",
        "POSTGRES_PORT",
        "POSTGRES_LITELLM_USER",
        "POSTGRES_LITELLM_PASSWORD",
        "POSTGRES_LITELLM_DATABASE",
        "QDRANT_PUBLIC_URL",
        "QDRANT_INTERNAL_HTTP_URL",
        "QDRANT_INTERNAL_GRPC_ENDPOINT",
        "QDRANT_API_KEY",
        "LITELLM_PUBLIC_URL",
        "LITELLM_INTERNAL_URL",
        "LITELLM_API_KEY",
    )
    migration = (
        "POSTGRES_EXTERNAL_HOST",
        "POSTGRES_INTERNAL_HOST",
        "POSTGRES_PORT",
        "POSTGRES_ADMIN_USER",
        "POSTGRES_ADMIN_PASSWORD",
        "POSTGRES_ADMIN_DATABASE",
        "POSTGRES_LITELLM_USER",
        "POSTGRES_LITELLM_DATABASE",
    )

    assert DOCUMENTED_ENVIRONMENT_VARIABLES == documented
    assert RUNTIME_ENVIRONMENT_VARIABLES == runtime
    assert POSTGRES_MIGRATION_ENVIRONMENT_VARIABLES == migration
    assert RuntimeSettings.environment_names == runtime
    assert PostgresMigrationSettings.environment_names == migration
    assert len(documented) == 16
    assert len(RuntimeSettings.model_fields) == 13
    assert len(PostgresMigrationSettings.model_fields) == 8
    assert (
        tuple(
            str(field.validation_alias)
            for field in RuntimeSettings.model_fields.values()
        )
        == runtime
    )
    assert (
        tuple(
            str(field.validation_alias)
            for field in PostgresMigrationSettings.model_fields.values()
        )
        == migration
    )


def test_runtime_settings_do_not_declare_or_parse_admin_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_ADMIN_USER", "unit-test-operator-user")
    monkeypatch.setenv("POSTGRES_ADMIN_PASSWORD", "unit-test-operator-password")
    monkeypatch.setenv("POSTGRES_ADMIN_DATABASE", "unit-test-operator-database")

    settings = RuntimeSettings()

    assert not hasattr(settings, "postgres_admin_user")
    assert not hasattr(settings, "postgres_admin_password")
    assert not hasattr(settings, "postgres_admin_database")
    assert not any("ADMIN" in name for name in settings.environment_names)


def test_sensitive_values_are_secret_types_and_redacted() -> None:
    fake_admin_password = "unit-test-admin-password-marker"
    fake_password = "unit-test-password-marker"
    fake_qdrant_key = "unit-test-qdrant-marker"
    fake_litellm_key = "unit-test-litellm-marker"
    runtime = make_runtime_settings(
        POSTGRES_LITELLM_PASSWORD=fake_password,
        QDRANT_API_KEY=fake_qdrant_key,
        LITELLM_API_KEY=fake_litellm_key,
    )
    migration = make_migration_settings(
        POSTGRES_ADMIN_PASSWORD=fake_admin_password,
    )

    assert runtime.postgres_password is not None
    assert runtime.qdrant_api_key is not None
    assert runtime.litellm_api_key is not None
    assert migration.postgres_admin_password is not None
    rendered = repr((runtime, migration))
    assert fake_admin_password not in rendered
    assert fake_password not in rendered
    assert fake_qdrant_key not in rendered
    assert fake_litellm_key not in rendered
    assert str(migration.postgres_admin_password) == "**********"
    assert str(runtime.postgres_password) == "**********"


def test_admin_settings_are_required_only_by_migration_settings() -> None:
    runtime = make_runtime_settings(
        POSTGRES_EXTERNAL_HOST="postgres.example.invalid",
        POSTGRES_PORT=5432,
        POSTGRES_LITELLM_USER="app-user",
        POSTGRES_LITELLM_PASSWORD="unit-test-app-password",
        POSTGRES_LITELLM_DATABASE="application-database",
        QDRANT_PUBLIC_URL="https://qdrant.example.invalid",
        QDRANT_API_KEY="unit-test-qdrant-key",
        LITELLM_PUBLIC_URL="https://litellm.example.invalid",
        LITELLM_API_KEY="unit-test-litellm-key",
    )
    migration = make_migration_settings(
        POSTGRES_EXTERNAL_HOST="postgres.example.invalid",
        POSTGRES_PORT=5432,
        POSTGRES_LITELLM_USER="app-user",
        POSTGRES_LITELLM_DATABASE="application-database",
    )

    assert runtime.missing_for_runtime() == ()
    assert migration.missing_for_migration() == (
        "POSTGRES_ADMIN_USER",
        "POSTGRES_ADMIN_PASSWORD",
        "POSTGRES_ADMIN_DATABASE",
    )
    runtime.require_runtime()
    with pytest.raises(ConfigurationError) as caught:
        migration.require_migration()
    assert str(caught.value) == (
        "Missing required environment variable(s): POSTGRES_ADMIN_USER, "
        "POSTGRES_ADMIN_PASSWORD, POSTGRES_ADMIN_DATABASE"
    )


def test_operator_postgres_settings_resolve_without_runtime_password() -> None:
    fake_admin_password = "unit-test-admin-password-marker"
    settings = make_migration_settings(
        POSTGRES_INTERNAL_HOST="postgres.internal",
        POSTGRES_PORT=5432,
        POSTGRES_ADMIN_USER="operator-user",
        POSTGRES_ADMIN_PASSWORD=fake_admin_password,
        POSTGRES_ADMIN_DATABASE="application-database",
        POSTGRES_LITELLM_USER="application-user",
        POSTGRES_LITELLM_DATABASE="application-database",
    )

    endpoint = settings.require_migration()

    assert endpoint.host == "postgres.internal"
    assert endpoint.port == 5432
    assert settings.missing_for_migration() == ()
    assert not hasattr(settings, "postgres_password")
    assert fake_admin_password not in repr(settings)


def test_operator_postgres_database_must_match_application_database_safely() -> None:
    admin_database = "operator-database-marker"
    application_database = "application-database-marker"
    settings = make_migration_settings(
        POSTGRES_EXTERNAL_HOST="postgres.example.invalid",
        POSTGRES_PORT=5432,
        POSTGRES_ADMIN_USER="operator-user",
        POSTGRES_ADMIN_PASSWORD="unit-test-admin-password",
        POSTGRES_ADMIN_DATABASE=admin_database,
        POSTGRES_LITELLM_USER="application-user",
        POSTGRES_LITELLM_DATABASE=application_database,
    )

    with pytest.raises(ConfigurationError) as caught:
        settings.require_migration()

    message = str(caught.value)
    assert "POSTGRES_ADMIN_DATABASE" in message
    assert "POSTGRES_LITELLM_DATABASE" in message
    assert admin_database not in message
    assert application_database not in message


def test_operator_postgres_identity_must_differ_from_application_identity() -> None:
    user_marker = "shared-user-marker"
    settings = make_migration_settings(
        POSTGRES_EXTERNAL_HOST="postgres.example.invalid",
        POSTGRES_PORT=5432,
        POSTGRES_ADMIN_USER=user_marker,
        POSTGRES_ADMIN_PASSWORD="unit-test-admin-password",
        POSTGRES_ADMIN_DATABASE="application-database",
        POSTGRES_LITELLM_USER=user_marker,
        POSTGRES_LITELLM_DATABASE="application-database",
    )

    with pytest.raises(ConfigurationError) as caught:
        settings.require_migration()

    message = str(caught.value)
    assert "POSTGRES_ADMIN_USER" in message
    assert "POSTGRES_LITELLM_USER" in message
    assert user_marker not in message


def test_internal_endpoints_take_precedence_and_urls_are_normalized() -> None:
    settings = make_runtime_settings(
        POSTGRES_EXTERNAL_HOST="postgres.example.invalid",
        POSTGRES_INTERNAL_HOST="postgres.internal",
        POSTGRES_PORT=5432,
        POSTGRES_LITELLM_USER="app-user",
        POSTGRES_LITELLM_PASSWORD="unit-test-password",
        POSTGRES_LITELLM_DATABASE="litellm",
        QDRANT_PUBLIC_URL="https://qdrant.example.invalid/",
        QDRANT_INTERNAL_HTTP_URL="http://qdrant.internal:6333/",
        QDRANT_API_KEY="unit-test-qdrant-key",
        LITELLM_PUBLIC_URL="https://litellm.example.invalid/",
        LITELLM_INTERNAL_URL="http://litellm.internal:4000/",
        LITELLM_API_KEY="unit-test-litellm-key",
    )

    endpoints = settings.require_runtime()

    assert endpoints.postgres_host == "postgres.internal"
    assert endpoints.postgres_port == 5432
    assert endpoints.qdrant_http_url == "http://qdrant.internal:6333"
    assert endpoints.litellm_url == "http://litellm.internal:4000"
    assert settings.safe_status() == {
        "postgres_endpoint": "internal",
        "qdrant_endpoint": "internal",
        "litellm_endpoint": "internal",
        "postgres_credentials_present": True,
        "qdrant_credential_present": True,
        "litellm_credential_present": True,
    }


def test_missing_configuration_reports_names_only_and_postgres_is_independent() -> None:
    settings = make_runtime_settings(
        POSTGRES_EXTERNAL_HOST="postgres.example.invalid",
        POSTGRES_PORT=5432,
        POSTGRES_LITELLM_USER="app-user",
        POSTGRES_LITELLM_PASSWORD="unit-test-password",
        POSTGRES_LITELLM_DATABASE="litellm",
    )

    postgres = settings.require_postgres()
    assert postgres.host == "postgres.example.invalid"
    assert postgres.port == 5432

    with pytest.raises(ConfigurationError) as caught:
        settings.require_runtime()
    message = str(caught.value)
    assert "QDRANT_INTERNAL_HTTP_URL or QDRANT_PUBLIC_URL" in message
    assert "QDRANT_API_KEY" in message
    assert "LITELLM_INTERNAL_URL or LITELLM_PUBLIC_URL" in message
    assert "LITELLM_API_KEY" in message
    assert "unit-test-password" not in message
    assert "postgres.example.invalid" not in message


def test_settings_do_not_enable_dotenv_loading() -> None:
    assert RuntimeSettings.model_config.get("env_file") is None
    assert PostgresMigrationSettings.model_config.get("env_file") is None
