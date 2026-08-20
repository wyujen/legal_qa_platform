from __future__ import annotations

import ast
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from legal_qa_platform.adapters.observability import NoopObservability
from legal_qa_platform.api.app import create_app
from legal_qa_platform.config.settings import (
    DOCUMENTED_ENVIRONMENT_VARIABLES,
    RuntimeSettings,
)
from legal_qa_platform.container import ApplicationContainer
from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.domain.qa import ChatResponse
from legal_qa_platform.domain.retrieval import RetrievalResult
from legal_qa_platform.ports.models import ChatCompletion, ChatMessage
from legal_qa_platform.services.conversation import ConversationService
from legal_qa_platform.services.qa import QaService


def make_profile() -> RagProfile:
    return RagProfile(
        embedding_dimension=2,
        candidate_k=1,
        top_k=1,
        min_score=0.0,
        conversation_message_limit=2,
        chat_max_tokens=111,
    )


def make_result() -> RetrievalResult:
    return RetrievalResult(
        provision_id=9,
        document_name="本地測試法規",
        article_no="第九條",
        title="申請期限",
        content="申請人應於七日內提出文件。",
        source_url="https://example.invalid/law",
        content_hash="a" * 64,
        record_hash="b" * 64,
        embedding_input_hash="c" * 64,
        vector_score=0.9,
        keyword_score=1.0,
        final_score=0.935,
        rank=1,
    )


class FakeQaRepository:
    def __init__(
        self,
        *,
        fail_start_log: bool = False,
        ready: bool = True,
        snapshot_ready: bool = True,
    ) -> None:
        self.conversation_id = UUID("00000000-0000-0000-0000-000000000009")
        self.fail_start_log = fail_start_log
        self.ready = ready
        self.snapshot_ready = snapshot_ready
        self.messages: list[tuple[str, str, UUID | None]] = []
        self.start_log_attempts = 0
        self.start_log_values: dict[str, object] | None = None
        self.finished_runs: list[dict[str, Any]] = []
        self.retrieval_rows: list[Mapping[str, Any]] = []

    async def create_conversation(
        self,
        *,
        user_id: str | None = None,
        conversation_id: UUID | None = None,
    ) -> UUID:
        del user_id
        return conversation_id or self.conversation_id

    async def conversation_status(self, conversation_id: UUID) -> str | None:
        return "active" if conversation_id == self.conversation_id else None

    async def recent_messages(
        self,
        _conversation_id: UUID,
        *,
        limit: int,
    ) -> list[dict[str, str]]:
        del limit
        return []

    async def append_message(
        self,
        _conversation_id: UUID,
        *,
        role: str,
        content: str,
        query_id: UUID | None = None,
    ) -> UUID:
        self.messages.append((role, content, query_id))
        return uuid4()

    async def start_qa_run(
        self,
        *,
        query_id: UUID,
        conversation_id: UUID | None,
        trace_id: str | None,
        profile_name: str,
        prompt_name: str,
        normalization_version: str,
        chat_model: str,
        embedding_model: str,
        vector_collection: str,
        question: str,
        normalized_question: str,
    ) -> None:
        self.start_log_attempts += 1
        self.start_log_values = {
            "query_id": query_id,
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "profile_name": profile_name,
            "prompt_name": prompt_name,
            "normalization_version": normalization_version,
            "chat_model": chat_model,
            "embedding_model": embedding_model,
            "vector_collection": vector_collection,
            "question": question,
            "normalized_question": normalized_question,
        }
        if self.fail_start_log:
            raise RuntimeError("simulated log outage")

    async def finish_qa_run(
        self,
        _query_id: UUID,
        *,
        response: Mapping[str, Any] | None,
        stage_latencies_ms: Mapping[str, int | float],
        error_category: str | None = None,
    ) -> None:
        self.finished_runs.append(
            {
                "response": response,
                "stage_latencies_ms": dict(stage_latencies_ms),
                "error_category": error_category,
            }
        )

    async def record_qa_retrievals(
        self,
        _query_id: UUID,
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        self.retrieval_rows.extend(rows)

    async def save_feedback(self, **_values: object) -> UUID:
        return UUID("00000000-0000-0000-0000-000000000010")

    async def is_ready(self) -> bool:
        return self.ready

    async def has_published_snapshot(
        self,
        *,
        embedding_model: str,
        embedding_dimension: int,
        vector_collection: str,
    ) -> bool:
        del embedding_model, embedding_dimension, vector_collection
        return self.snapshot_ready

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeRetrieval:
    def __init__(self, results: Sequence[RetrievalResult]) -> None:
        self.results = list(results)
        self.calls: list[str] = []

    async def retrieve(
        self,
        normalized_question: str,
        *,
        trace: object | None = None,
        stage_latencies_ms: dict[str, float] | None = None,
    ) -> list[RetrievalResult]:
        del trace
        self.calls.append(normalized_question)
        if stage_latencies_ms is not None:
            stage_latencies_ms["retrieval_test"] = 0.1
        return list(self.results)


class FakeChatModel:
    def __init__(self, responses: Sequence[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        max_tokens: int,
        response_schema: Mapping[str, Any],
    ) -> ChatCompletion:
        self.calls.append(
            {
                "messages": list(messages),
                "model": model,
                "max_tokens": max_tokens,
                "response_schema": dict(response_schema),
            }
        )
        return ChatCompletion(content=self.responses.pop(0), model=model)


@pytest.mark.asyncio
async def test_no_hit_skips_llm_and_database_run_logging_is_fail_open() -> None:
    profile = make_profile()
    repository = FakeQaRepository(fail_start_log=True)
    retrieval = FakeRetrieval([])
    chat_model = FakeChatModel([])
    service = QaService(
        repository=repository,
        retrieval=retrieval,  # type: ignore[arg-type]
        chat_model=chat_model,
        conversations=ConversationService(repository, message_limit=2),
        observability=NoopObservability(),
        profile=profile,
    )

    answer = await service.answer("申請期限為何？")

    assert answer.response is not None
    assert answer.response.can_answer is False
    assert answer.response.citations == []
    assert chat_model.calls == []
    assert repository.start_log_attempts == 1
    assert repository.finished_runs == []
    assert [role for role, _content, _query_id in repository.messages] == [
        "user",
        "assistant",
    ]


@pytest.mark.asyncio
async def test_qa_repairs_once_and_enriches_only_allowlisted_citations() -> None:
    profile = make_profile()
    repository = FakeQaRepository()
    retrieval = FakeRetrieval([make_result()])
    valid_response = json.dumps(
        {
            "can_answer": True,
            "summary": "應於七日內提出申請。",
            "conditions": ["備妥文件"],
            "exceptions": [],
            "missing_information": [],
            "citations": [{"provision_id": 9}, {"provision_id": 999}],
        },
        ensure_ascii=False,
    )
    chat_model = FakeChatModel(["not-json", valid_response])
    service = QaService(
        repository=repository,
        retrieval=retrieval,  # type: ignore[arg-type]
        chat_model=chat_model,
        conversations=ConversationService(repository, message_limit=2),
        observability=NoopObservability(),
        profile=profile,
    )

    answer = await service.answer("申請期限為何？")

    assert answer.response is not None
    assert answer.response.can_answer is True
    assert [item.model_dump() for item in answer.response.citations] == [
        {
            "provision_id": 9,
            "document_name": "本地測試法規",
            "article_no": "第九條",
        }
    ]
    assert len(chat_model.calls) == 2
    assert all(call["max_tokens"] == 111 for call in chat_model.calls)
    repair_messages = chat_model.calls[1]["messages"]
    assert "JSON Schema" in repair_messages[-1].content
    assert len(repository.retrieval_rows) == 1
    assert repository.retrieval_rows[0]["provision_id"] == 9
    assert repository.retrieval_rows[0]["official_content_hash"] == "a" * 64
    assert repository.start_log_values is not None
    assert repository.start_log_values["normalization_version"] == (
        "legal_qa_platform-normalization-v1"
    )
    assert len(repository.finished_runs) == 1
    assert repository.finished_runs[0]["error_category"] is None


class FakeProbe:
    def __init__(self, ready: bool, *, collection_ready: bool = True) -> None:
        self.ready = ready
        self.collection_ready = collection_ready

    async def is_ready(self) -> bool:
        return self.ready

    async def collection_is_ready(
        self,
        _name: str,
        *,
        dimension: int,
        distance: str = "Cosine",
    ) -> bool:
        del dimension, distance
        return self.collection_ready

    async def aclose(self) -> None:
        return None


class FakeApiQa:
    async def answer(
        self,
        question: str,
        *,
        conversation_id: str | None = None,
    ) -> ChatResponse:
        del conversation_id
        return ChatResponse(
            query_id=str(uuid4()),
            conversation_id=str(uuid4()),
            question=question,
            normalized_question=question,
            profile="platform-baseline-v1",
            response=None,
        )


def make_runtime_settings() -> RuntimeSettings:
    explicit: dict[str, object] = {
        name: None for name in DOCUMENTED_ENVIRONMENT_VARIABLES
    }
    return RuntimeSettings.model_validate(explicit)


def make_container(
    *,
    postgres: bool,
    published_snapshot: bool = True,
    qdrant: bool,
    qdrant_collection: bool = True,
    litellm: bool,
) -> ApplicationContainer:
    profile = make_profile()
    repository: Any = FakeQaRepository(
        ready=postgres,
        snapshot_ready=published_snapshot,
    )
    retrieval: Any = FakeRetrieval([])
    qdrant_probe: Any = FakeProbe(qdrant, collection_ready=qdrant_collection)
    litellm_probe: Any = FakeProbe(litellm)
    qa: Any = FakeApiQa()
    return ApplicationContainer(
        settings=make_runtime_settings(),
        profile=profile,
        repository=repository,
        qdrant=qdrant_probe,
        litellm=litellm_probe,
        retrieval=retrieval,
        conversations=ConversationService(repository, message_limit=2),
        qa=qa,
    )


@pytest.mark.parametrize(
    ("checks", "expected_status", "expected_body_status"),
    [
        ((True, True, True, True, True), 200, "ready"),
        ((True, True, False, False, True), 503, "not_ready"),
    ],
)
@pytest.mark.asyncio
async def test_fastapi_health_and_readiness(
    checks: tuple[bool, bool, bool, bool, bool],
    expected_status: int,
    expected_body_status: str,
) -> None:
    container = make_container(
        postgres=checks[0],
        published_snapshot=checks[1],
        qdrant=checks[2],
        qdrant_collection=checks[3],
        litellm=checks[4],
    )
    application = create_app(container, manage_lifecycle=False)

    transport = httpx.ASGITransport(app=application)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            health = await client.get("/health")
            readiness = await client.get("/ready")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "legal_qa_platform"}
    assert readiness.status_code == expected_status
    assert readiness.json()["status"] == expected_body_status
    assert readiness.json()["checks"] == {
        "postgresql": checks[0],
        "published_snapshot": checks[1],
        "qdrant": checks[2],
        "qdrant_collection": checks[3],
        "litellm": checks[4],
    }


@pytest.mark.asyncio
async def test_fastapi_validation_error_does_not_echo_rejected_input() -> None:
    application = create_app(
        make_container(postgres=True, qdrant=True, litellm=True),
        manage_lifecycle=False,
    )
    private_input_marker = "private-request-input-marker"

    transport = httpx.ASGITransport(app=application)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/chat",
                json={
                    "message": private_input_marker,
                    "unexpected": private_input_marker,
                },
            )

    assert response.status_code == 422
    assert response.json()["category"] == "request_validation"
    assert private_input_marker not in response.text
    assert response.json()["fields"] == [
        {"field": "unexpected", "category": "extra_forbidden"}
    ]


def test_streamlit_ui_is_a_rest_client_and_does_not_import_qa_services() -> None:
    ui_path = Path(__file__).resolve().parents[2] / (
        "src/legal_qa_platform/ui/streamlit_app.py"
    )
    source = ui_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any(name.startswith("legal_qa_platform") for name in imported_modules)
    assert "httpx" in imported_modules
    assert "httpx.post" in source
    assert '"/api/v1/chat"' in source
    assert '"/api/v1/feedback"' in source
    assert "QaService" not in source

    http_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "httpx"
    ]
    assert http_calls
    for call in http_calls:
        trust_env = next(
            (keyword.value for keyword in call.keywords if keyword.arg == "trust_env"),
            None,
        )
        assert isinstance(trust_env, ast.Constant)
        assert trust_env.value is False
