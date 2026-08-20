from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from legal_qa_platform.adapters.http_safety import HttpReadinessResult
from legal_qa_platform.config import RuntimeSettings
from legal_qa_platform.ports.models import ChatCompletion
from legal_qa_platform.ports.repositories import RepositoryReadinessResult
from scripts import smoke_test


class _Repository:
    def __init__(self, *, published: bool) -> None:
        self.published = published
        self.readiness_calls = 0
        self.snapshot_calls = 0

    async def readiness_status(self) -> RepositoryReadinessResult:
        self.readiness_calls += 1
        return RepositoryReadinessResult(category="ready")

    async def has_published_snapshot(self, **_kwargs: object) -> bool:
        self.snapshot_calls += 1
        return self.published


class _Qdrant:
    def __init__(self, *, collection_ready: bool) -> None:
        self.collection_ready = collection_ready
        self.readiness_calls = 0
        self.collection_calls = 0

    async def readiness_status(self) -> HttpReadinessResult:
        self.readiness_calls += 1
        return HttpReadinessResult(ready=True, category="ready", status_code=200)

    async def collection_is_ready(
        self,
        _collection: str,
        *,
        dimension: int,
    ) -> bool:
        assert dimension == 1_024
        self.collection_calls += 1
        return self.collection_ready


class _LiteLLM:
    def __init__(self) -> None:
        self.readiness_calls = 0
        self.embedding_calls = 0
        self.chat_calls = 0

    async def readiness_status(self) -> HttpReadinessResult:
        self.readiness_calls += 1
        return HttpReadinessResult(ready=True, category="ready", status_code=200)

    async def embed(
        self,
        _texts: list[str],
        *,
        model: str,
        expected_dimension: int,
    ) -> list[list[float]]:
        assert model == "bge-m3"
        self.embedding_calls += 1
        return [[0.0] * expected_dimension]

    async def complete(
        self,
        _messages: object,
        *,
        model: str,
        max_tokens: int,
        response_schema: object,
    ) -> ChatCompletion:
        assert model == "campus-qa"
        assert max_tokens == 512
        assert response_schema
        self.chat_calls += 1
        return ChatCompletion(
            content=(
                '{"can_answer":false,"summary":"參考條文不足。",'
                '"conditions":[],"exceptions":[],"missing_information":[],'
                '"citations":[]}'
            ),
            model=model,
        )


class _Container:
    def __init__(self, *, published: bool, collection_ready: bool) -> None:
        self.repository = _Repository(published=published)
        self.qdrant = _Qdrant(collection_ready=collection_ready)
        self.litellm = _LiteLLM()
        self.profile = SimpleNamespace(
            embedding_model="bge-m3",
            embedding_dimension=1_024,
            vector_collection="legal_provisions_bge_m3_v1",
            chat_model="campus-qa",
            chat_max_tokens=512,
        )

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _patch_container(
    monkeypatch: pytest.MonkeyPatch,
    container: _Container,
) -> None:
    def build(**_kwargs: object) -> Any:
        return container

    monkeypatch.setattr(smoke_test.ApplicationContainer, "build", build)


def test_smoke_parser_defaults_to_full_and_accepts_dependencies() -> None:
    parser = smoke_test.build_parser()

    assert parser.parse_args([]).phase == "full"
    assert parser.parse_args(["--phase", "dependencies"]).phase == "dependencies"


@pytest.mark.asyncio
async def test_dependencies_phase_skips_data_bootstrap_contracts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    container = _Container(published=False, collection_ready=False)
    _patch_container(monkeypatch, container)

    exit_code = await smoke_test.run_smoke(
        RuntimeSettings.model_construct(),
        Path("unused-profile.json"),
        phase="dependencies",
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert container.repository.readiness_calls == 1
    assert container.repository.snapshot_calls == 0
    assert container.qdrant.readiness_calls == 1
    assert container.qdrant.collection_calls == 0
    assert container.litellm.readiness_calls == 1
    assert container.litellm.embedding_calls == 1
    assert container.litellm.chat_calls == 1
    assert "[SKIP] PostgreSQL published snapshot phase=dependencies" in output
    assert "[SKIP] Qdrant collection contract phase=dependencies" in output
    assert "[FAIL]" not in output


@pytest.mark.asyncio
async def test_full_phase_remains_strict_for_bootstrap_contracts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    container = _Container(published=False, collection_ready=False)
    _patch_container(monkeypatch, container)

    exit_code = await smoke_test.run_smoke(
        RuntimeSettings.model_construct(),
        Path("unused-profile.json"),
        phase="full",
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert container.repository.snapshot_calls == 1
    assert container.qdrant.collection_calls == 1
    assert "[FAIL] PostgreSQL published snapshot missing" in output
    assert "[FAIL] Qdrant collection missing_or_mismatched" in output
    assert "[FAIL] smoke test failed checks=2" in output
