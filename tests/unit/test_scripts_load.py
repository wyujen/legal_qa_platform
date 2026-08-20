from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

from legal_qa_platform.config.settings import (
    DOCUMENTED_ENVIRONMENT_VARIABLES,
    RuntimeSettings,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import (  # noqa: E402
    evaluate,
    export_schemas,
    load_test,
    migrate,
    smoke_test,
    sync_laws,
)
from scripts.load_test import (  # noqa: E402
    RequestSample,
    parse_concurrency,
    summarize_level,
)


def _sample(
    *,
    success: bool,
    status: int | None,
    category: str | None,
    duration: float,
    stages: dict[str, float] | None = None,
) -> RequestSample:
    return RequestSample(
        status_code=status,
        duration_ms=duration,
        success=success,
        timeout=category == "timeout",
        error_category=category,
        stage_latencies_ms=stages or {},
        structured_valid=True if success else None,
        citation_allowlist_valid=True if success else None,
        answer_nonempty=True if success else None,
    )


def test_default_concurrency_levels_cover_required_escalation() -> None:
    args = load_test.build_parser().parse_args([])
    assert args.concurrency == (1, 5, 10, 20, 50, 100)
    assert args.stop_error_rate is None
    assert args.stop_on_gateway_quota is False


def test_concurrency_parser_requires_strictly_increasing_positive_levels() -> None:
    assert parse_concurrency("1,5,10") == (1, 5, 10)
    with pytest.raises(argparse.ArgumentTypeError):
        parse_concurrency("5,1")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_concurrency("1,1")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_concurrency("0,1")


def test_load_summary_separates_gateway_and_application_signals() -> None:
    samples = [
        _sample(
            success=True,
            status=200,
            category=None,
            duration=100.0,
            stages={"generation": 80.0, "total": 90.0},
        ),
        _sample(
            success=False,
            status=429,
            category="rate_limited",
            duration=50.0,
        ),
    ]

    summary = summarize_level(samples, concurrency=5, wall_seconds=1.0)
    signals = summary["capacity_signals"]

    assert summary["error_rate"] == 0.5
    assert isinstance(signals, dict)
    assert signals["gateway_quota_signal_count"] == 1
    assert signals["application_or_dependency_5xx_count"] == 0
    assert signals["attribution"] == "gateway_quota_signal"


def test_all_script_parsers_reject_credential_style_options() -> None:
    forbidden = {
        "--api-key",
        "--password",
        "--master-key",
        "--secret-file",
        "--token",
    }
    parsers = [
        migrate.build_parser(),
        sync_laws.build_parser(),
        smoke_test.build_parser(),
        evaluate.build_parser(),
        load_test.build_parser(),
        export_schemas.build_parser(),
    ]
    for parser in parsers:
        options = {
            option for action in parser._actions for option in action.option_strings
        }
        assert forbidden.isdisjoint(options)


def test_smoke_collection_probe_is_read_only() -> None:
    source = inspect.getsource(smoke_test.run_smoke)
    assert "collection_is_ready" in source
    assert "ensure_collection" not in source
    assert "has_published_snapshot" in source


def _settings_with_both_endpoint_families() -> RuntimeSettings:
    return RuntimeSettings.model_construct(
        postgres_external_host="EXTERNAL_HOST_MARKER",
        postgres_internal_host="INTERNAL_HOST_MARKER",
        postgres_port=5432,
        postgres_user="unit-test-user",
        postgres_password=SecretStr("PRIVATE_PASSWORD_MARKER"),
        postgres_database="unit-test-database",
        qdrant_public_url="https://public-qdrant.example.invalid",
        qdrant_internal_http_url="http://internal-qdrant.example.invalid",
        qdrant_internal_grpc_endpoint=None,
        qdrant_api_key=SecretStr("PRIVATE_QDRANT_MARKER"),
        litellm_public_url="https://public-litellm.example.invalid",
        litellm_internal_url="http://internal-litellm.example.invalid",
        litellm_api_key=SecretStr("PRIVATE_LITELLM_MARKER"),
    )


def test_smoke_endpoint_scope_can_select_public_without_changing_app_default() -> None:
    settings = _settings_with_both_endpoint_families()

    automatic = smoke_test.select_endpoint_scope(settings, "auto")
    public = smoke_test.select_endpoint_scope(settings, "public")
    internal = smoke_test.select_endpoint_scope(settings, "internal")

    assert automatic.postgres_host == "INTERNAL_HOST_MARKER"
    assert automatic.qdrant_http_url == "http://internal-qdrant.example.invalid"
    assert automatic.litellm_url == "http://internal-litellm.example.invalid"
    assert public.postgres_host == "EXTERNAL_HOST_MARKER"
    assert public.qdrant_http_url == "https://public-qdrant.example.invalid"
    assert public.litellm_url == "https://public-litellm.example.invalid"
    assert internal.postgres_host == "INTERNAL_HOST_MARKER"


def test_smoke_endpoint_selection_message_contains_families_only() -> None:
    settings = smoke_test.select_endpoint_scope(
        _settings_with_both_endpoint_families(),
        "public",
    )

    message = smoke_test.endpoint_selection_message(
        settings,
        requested_scope="public",
    )

    assert message == (
        "[INFO] endpoint selection scope=public "
        "postgres=external qdrant=public litellm=public"
    )
    assert "MARKER" not in message


def test_api_base_url_rejects_embedded_credentials() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        load_test.validate_api_base_url("https://user:password@example.invalid")
    with pytest.raises(argparse.ArgumentTypeError):
        load_test.validate_api_base_url("https://example.invalid:not-a-port")


@pytest.mark.asyncio
async def test_load_test_http_client_ignores_undocumented_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    async def failed_preflight(_client: object) -> bool:
        return False

    monkeypatch.setattr(load_test.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(load_test, "_preflight", failed_preflight)

    levels, reason = await load_test.run_load_test(
        api_base_url="https://api.example.invalid",
        scenario="health",
        questions=["測試"],
        profile_name="platform-baseline-v1",
        concurrency_levels=[1],
        requests_per_level=1,
        warmup_requests=0,
        timeout_seconds=1.0,
        stop_error_rate=None,
        stop_on_gateway_quota=False,
    )

    assert levels == []
    assert reason == "preflight_failed"
    assert captured["trust_env"] is False


def test_offline_migration_handoff_does_not_read_or_print_runtime_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in DOCUMENTED_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    sentinel = "SENTINEL_DO_NOT_PRINT"
    monkeypatch.setenv("POSTGRES_LITELLM_PASSWORD", sentinel)

    exit_code = migrate.main([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "database_unchanged=true" in output
    assert "POSTGRES_" not in output
    assert sentinel not in output
