from __future__ import annotations

import asyncio
import selectors
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest

from legal_qa_platform import async_runtime
from legal_qa_platform.api import server

PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def _answer() -> int:
    return 42


def test_run_async_uses_selector_loop_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(async_runtime.sys, "platform", "win32")

    async def inspect_loop() -> tuple[asyncio.AbstractEventLoop, bool]:
        loop = asyncio.get_running_loop()
        selector = getattr(loop, "_selector", None)
        return loop, isinstance(selector, selectors.SelectSelector)

    loop, uses_select_selector = async_runtime.run_async(inspect_loop())

    assert isinstance(loop, asyncio.SelectorEventLoop)
    assert uses_select_selector is True
    assert loop.is_closed()


def test_run_async_keeps_standard_asyncio_behavior_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: Coroutine[Any, Any, int] | None = None

    def fake_run(main: Coroutine[Any, Any, int]) -> int:
        nonlocal received
        received = main
        main.close()
        return 42

    monkeypatch.setattr(async_runtime.sys, "platform", "linux")
    monkeypatch.setattr(async_runtime.asyncio, "run", fake_run)

    assert async_runtime.run_async(_answer()) == 42
    assert received is not None


def test_api_server_runs_inside_application_owned_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: Coroutine[Any, Any, int] | None = None

    for name, value in {
        "POSTGRES_EXTERNAL_HOST": "postgres.example.invalid",
        "POSTGRES_PORT": "5432",
        "POSTGRES_LITELLM_USER": "application-role",
        "POSTGRES_LITELLM_PASSWORD": "unit-test-password",
        "POSTGRES_LITELLM_DATABASE": "application-database",
        "QDRANT_PUBLIC_URL": "https://qdrant.example.invalid",
        "QDRANT_API_KEY": "unit-test-qdrant-key",
        "LITELLM_PUBLIC_URL": "https://litellm.example.invalid",
        "LITELLM_API_KEY": "unit-test-litellm-key",
    }.items():
        monkeypatch.setenv(name, value)

    def fake_run(main: Coroutine[Any, Any, int]) -> int:
        nonlocal received
        received = main
        main.close()
        return 17

    monkeypatch.setattr(server, "run_async", fake_run)

    result = server.main(["--host", "127.0.0.1", "--port", "8765"])

    assert result == 17
    assert received is not None


@pytest.mark.parametrize(
    "script_name",
    ("evaluate.py", "load_test.py", "migrate.py", "smoke_test.py", "sync_laws.py"),
)
def test_async_operator_scripts_use_the_shared_runner(script_name: str) -> None:
    source = (PROJECT_ROOT / "scripts" / script_name).read_text(encoding="utf-8")

    assert "from legal_qa_platform.async_runtime import run_async" in source
    assert "asyncio.run(" not in source
