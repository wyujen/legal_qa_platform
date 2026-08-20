from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, cast

import pytest
from pydantic import SecretStr

from legal_qa_platform.api import server
from legal_qa_platform.config import (
    ENDPOINT_SCOPE_CHOICES,
    PostgresMigrationSettings,
    RuntimeSettings,
    missing_for_migration_scope,
    missing_for_runtime_scope,
    postgres_endpoint_family,
    runtime_endpoint_families,
    select_endpoint_scope,
)
from scripts import migrate, smoke_test, sync_laws


def _runtime_settings() -> RuntimeSettings:
    return RuntimeSettings.model_construct(
        postgres_external_host="EXTERNAL_POSTGRES_MARKER",
        postgres_internal_host="INTERNAL_POSTGRES_MARKER",
        postgres_port=5432,
        postgres_user="application-role",
        postgres_password=SecretStr("unit-test-password"),
        postgres_database="application-database",
        qdrant_public_url="https://public-qdrant.example.invalid",
        qdrant_internal_http_url="http://internal-qdrant.example.invalid",
        qdrant_internal_grpc_endpoint="internal-qdrant.example.invalid:6334",
        qdrant_api_key=SecretStr("unit-test-qdrant-key"),
        litellm_public_url="https://public-litellm.example.invalid",
        litellm_internal_url="http://internal-litellm.example.invalid",
        litellm_api_key=SecretStr("unit-test-litellm-key"),
    )


def _migration_settings() -> PostgresMigrationSettings:
    return PostgresMigrationSettings.model_construct(
        postgres_external_host="EXTERNAL_POSTGRES_MARKER",
        postgres_internal_host="INTERNAL_POSTGRES_MARKER",
        postgres_port=5432,
        postgres_admin_user="migration-role",
        postgres_admin_password=SecretStr("unit-test-admin-password"),
        postgres_admin_database="application-database",
        postgres_user="application-role",
        postgres_database="application-database",
    )


def test_runtime_endpoint_scope_is_pure_and_auto_remains_internal_first() -> None:
    settings = _runtime_settings()

    automatic = select_endpoint_scope(settings, "auto")
    public = select_endpoint_scope(settings, "public")
    internal = select_endpoint_scope(settings, "internal")

    assert automatic is settings
    assert automatic.postgres_host == "INTERNAL_POSTGRES_MARKER"
    assert public.postgres_host == "EXTERNAL_POSTGRES_MARKER"
    assert public.qdrant_http_url == "https://public-qdrant.example.invalid"
    assert public.qdrant_internal_grpc_endpoint is None
    assert public.litellm_url == "https://public-litellm.example.invalid"
    assert internal.postgres_host == "INTERNAL_POSTGRES_MARKER"
    assert internal.qdrant_http_url == "http://internal-qdrant.example.invalid"
    assert internal.litellm_url == "http://internal-litellm.example.invalid"
    assert settings.postgres_internal_host == "INTERNAL_POSTGRES_MARKER"
    assert settings.postgres_external_host == "EXTERNAL_POSTGRES_MARKER"


def test_migration_endpoint_scope_uses_the_same_selector() -> None:
    settings = _migration_settings()

    public = select_endpoint_scope(settings, "public")
    internal = select_endpoint_scope(settings, "internal")

    assert public.postgres_host == "EXTERNAL_POSTGRES_MARKER"
    assert postgres_endpoint_family(public) == "external"
    assert internal.postgres_host == "INTERNAL_POSTGRES_MARKER"
    assert postgres_endpoint_family(internal) == "internal"


def test_explicit_scope_reports_only_the_selected_missing_names() -> None:
    runtime = select_endpoint_scope(
        _runtime_settings().model_copy(
            update={
                "postgres_external_host": None,
                "qdrant_public_url": None,
                "litellm_public_url": None,
            }
        ),
        "public",
    )
    migration = select_endpoint_scope(
        _migration_settings().model_copy(update={"postgres_external_host": None}),
        "public",
    )

    assert missing_for_runtime_scope(runtime, "public") == (
        "POSTGRES_EXTERNAL_HOST",
        "QDRANT_PUBLIC_URL",
        "LITELLM_PUBLIC_URL",
    )
    assert missing_for_migration_scope(migration, "public") == (
        "POSTGRES_EXTERNAL_HOST",
    )


def test_endpoint_family_diagnostics_never_include_endpoint_values() -> None:
    families = runtime_endpoint_families(
        select_endpoint_scope(_runtime_settings(), "public")
    )

    assert families.postgres == "external"
    assert families.qdrant == "public"
    assert families.litellm == "public"
    assert "MARKER" not in repr(families)
    assert "example.invalid" not in repr(families)


def test_selector_rejects_unknown_scope_defensively() -> None:
    with pytest.raises(ValueError, match="Unsupported endpoint scope"):
        select_endpoint_scope(_runtime_settings(), cast(Any, "unexpected"))


def test_live_command_parsers_share_the_same_endpoint_scope_contract() -> None:
    parsers = (
        migrate.build_parser(),
        smoke_test.build_parser(),
        sync_laws.build_parser(),
        server.build_parser(),
    )

    for parser in parsers:
        action = next(
            item
            for item in parser._actions
            if "--endpoint-scope" in item.option_strings
        )
        assert action.default == "auto"
        assert tuple(action.choices) == ENDPOINT_SCOPE_CHOICES


def test_api_main_selects_settings_without_mutating_endpoint_environment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    internal_marker = "INTERNAL_API_PROCESS_MARKER"
    public_marker = "PUBLIC_API_PROCESS_MARKER"
    monkeypatch.setenv("POSTGRES_INTERNAL_HOST", internal_marker)
    monkeypatch.setenv("POSTGRES_EXTERNAL_HOST", public_marker)
    monkeypatch.setenv(
        "QDRANT_INTERNAL_HTTP_URL", "http://internal-api-qdrant.example.invalid"
    )
    monkeypatch.setenv("QDRANT_PUBLIC_URL", "https://public-api-qdrant.example.invalid")
    monkeypatch.setenv(
        "LITELLM_INTERNAL_URL", "http://internal-api-litellm.example.invalid"
    )
    monkeypatch.setenv(
        "LITELLM_PUBLIC_URL", "https://public-api-litellm.example.invalid"
    )
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_LITELLM_USER", "application-role")
    monkeypatch.setenv("POSTGRES_LITELLM_PASSWORD", "unit-test-password")
    monkeypatch.setenv("POSTGRES_LITELLM_DATABASE", "application-database")
    monkeypatch.setenv("QDRANT_API_KEY", "unit-test-qdrant-key")
    monkeypatch.setenv("LITELLM_API_KEY", "unit-test-litellm-key")
    captured: dict[str, object] = {}

    async def fake_serve(**kwargs: object) -> int:
        captured.update(kwargs)
        return 19

    def fake_run(coroutine: Coroutine[Any, Any, int]) -> int:
        return asyncio.run(coroutine)

    monkeypatch.setattr(server, "serve", fake_serve)
    monkeypatch.setattr(server, "run_async", fake_run)

    result = server.main(["--endpoint-scope", "public"])
    output = capsys.readouterr().out

    selected = cast(RuntimeSettings, captured["settings"])
    assert result == 19
    assert selected.postgres_internal_host is None
    assert selected.postgres_external_host == public_marker
    assert selected.qdrant_internal_http_url is None
    assert selected.litellm_internal_url is None
    assert internal_marker not in output
    assert public_marker not in output
    assert "scope=public postgres=external qdrant=public litellm=public" in output
    assert RuntimeSettings().postgres_internal_host == internal_marker


def test_api_main_reports_selected_missing_names_without_starting_server(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in RuntimeSettings.environment_names:
        monkeypatch.delenv(name, raising=False)
    invoked = False

    def unexpected_run(_coroutine: Coroutine[Any, Any, int]) -> int:
        nonlocal invoked
        invoked = True
        return 0

    monkeypatch.setattr(server, "run_async", unexpected_run)

    result = server.main(["--endpoint-scope", "public"])
    output = capsys.readouterr().out

    assert result == 2
    assert invoked is False
    assert "POSTGRES_EXTERNAL_HOST" in output
    assert "QDRANT_PUBLIC_URL" in output
    assert "LITELLM_PUBLIC_URL" in output
    assert "POSTGRES_INTERNAL_HOST or POSTGRES_EXTERNAL_HOST" not in output


@pytest.mark.asyncio
async def test_api_serve_passes_selected_settings_to_application_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = select_endpoint_scope(_runtime_settings(), "public")
    application = object()
    captured: dict[str, object] = {}

    def fake_create_app(**kwargs: object) -> object:
        captured["factory_settings"] = kwargs["settings"]
        return application

    class FakeConfig:
        def __init__(self, app: object, **kwargs: object) -> None:
            captured["application"] = app
            captured.update(kwargs)

    class FakeServer:
        def __init__(self, config: object) -> None:
            captured["config"] = config

        async def serve(self) -> None:
            captured["served"] = True

    monkeypatch.setattr(server, "create_app", fake_create_app)
    monkeypatch.setattr(server.uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(server.uvicorn, "Server", FakeServer)

    result = await server.serve(
        settings=settings,
        host="127.0.0.1",
        port=8765,
        access_log=False,
    )

    assert result == 0
    assert captured["factory_settings"] is settings
    assert captured["application"] is application
    assert captured["served"] is True
