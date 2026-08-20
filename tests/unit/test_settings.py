from __future__ import annotations

import pytest

from legal_qa_platform.config.settings import (
    DOCUMENTED_ENVIRONMENT_VARIABLES,
    RuntimeSettings,
)
from legal_qa_platform.errors import ConfigurationError


def make_settings(**updates: object) -> RuntimeSettings:
    """Construct settings entirely from explicit test inputs, never process env."""

    values: dict[str, object] = {
        name: None for name in DOCUMENTED_ENVIRONMENT_VARIABLES
    }
    values.update(updates)
    return RuntimeSettings.model_validate(values)


def test_environment_contract_contains_exactly_the_thirteen_approved_names() -> None:
    expected = (
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

    assert DOCUMENTED_ENVIRONMENT_VARIABLES == expected
    assert RuntimeSettings.environment_names == expected
    assert len(expected) == 13
    aliases = {
        str(field.validation_alias) for field in RuntimeSettings.model_fields.values()
    }
    assert aliases == set(expected)


def test_sensitive_values_are_secret_types_and_redacted() -> None:
    fake_password = "unit-test-password-marker"
    fake_qdrant_key = "unit-test-qdrant-marker"
    fake_litellm_key = "unit-test-litellm-marker"
    settings = make_settings(
        POSTGRES_LITELLM_PASSWORD=fake_password,
        QDRANT_API_KEY=fake_qdrant_key,
        LITELLM_API_KEY=fake_litellm_key,
    )

    assert settings.postgres_password is not None
    assert settings.qdrant_api_key is not None
    assert settings.litellm_api_key is not None
    rendered = repr(settings)
    assert fake_password not in rendered
    assert fake_qdrant_key not in rendered
    assert fake_litellm_key not in rendered
    assert str(settings.postgres_password) == "**********"


def test_internal_endpoints_take_precedence_and_urls_are_normalized() -> None:
    settings = make_settings(
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
    settings = make_settings(
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
