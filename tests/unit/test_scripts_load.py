from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path

import pytest

from legal_qa_platform.config.settings import DOCUMENTED_ENVIRONMENT_VARIABLES

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


def test_api_base_url_rejects_embedded_credentials() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        load_test.validate_api_base_url("https://user:password@example.invalid")
    with pytest.raises(argparse.ArgumentTypeError):
        load_test.validate_api_base_url("https://example.invalid:not-a-port")


def test_missing_runtime_output_never_prints_present_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in DOCUMENTED_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    sentinel = "SENTINEL_DO_NOT_PRINT"
    monkeypatch.setenv("POSTGRES_LITELLM_PASSWORD", sentinel)

    exit_code = migrate.main([])
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "POSTGRES_PORT" in output
    assert sentinel not in output
