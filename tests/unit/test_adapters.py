from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from legal_qa_platform.adapters.litellm import LiteLLMGateway
from legal_qa_platform.adapters.qdrant import QdrantVectorStore
from legal_qa_platform.errors import ExternalServiceError
from legal_qa_platform.ports.models import ChatMessage
from legal_qa_platform.ports.vector_store import VectorPoint


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_factory",
    [LiteLLMGateway, QdrantVectorStore],
)
async def test_owned_dependency_http_clients_ignore_undocumented_environment(
    adapter_factory: Callable[..., object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    adapter = adapter_factory(
        "https://dependency.example.invalid",
        SecretStr("unit-test-key"),
    )
    await adapter.aclose()  # type: ignore[attr-defined]

    assert captured["trust_env"] is False


@pytest.mark.asyncio
async def test_litellm_embedding_and_chat_requests_follow_gateway_contract() -> None:
    requests: list[tuple[str, dict[str, Any]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path == "/v1/embeddings":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.0, 1.0]},
                        {"index": 0, "embedding": [1.0, 0.0]},
                    ]
                },
            )
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(
                200,
                json={
                    "id": "request-1",
                    "model": "campus-qa",
                    "choices": [{"message": {"content": "{}"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                },
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://litellm.example.invalid",
        transport=transport,
    ) as client:
        gateway = LiteLLMGateway(
            "https://litellm.example.invalid",
            SecretStr("unit-test-key"),
            client=client,
        )
        vectors = await gateway.embed(
            ["第一段", "第二段"],
            model="bge-m3",
            expected_dimension=2,
        )
        completion = await gateway.complete(
            [ChatMessage(role="user", content="測試問題")],
            model="campus-qa",
            max_tokens=321,
            response_schema={"type": "object", "additionalProperties": False},
        )

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert completion.model == "campus-qa"
    assert completion.request_id == "request-1"
    assert completion.usage == {"prompt_tokens": 10, "completion_tokens": 2}
    embedding_request = requests[0][1]
    assert embedding_request == {
        "model": "bge-m3",
        "input": ["第一段", "第二段"],
    }
    chat_request = requests[1][1]
    assert chat_request["max_tokens"] == 321
    assert chat_request["temperature"] == 0
    assert chat_request["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "legal_qa_answer",
            "strict": True,
            "schema": {"type": "object", "additionalProperties": False},
        },
    }


@pytest.mark.asyncio
async def test_litellm_rejects_wrong_dimension_and_redacts_http_body() -> None:
    async def wrong_dimension(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0]}]},
        )

    async with httpx.AsyncClient(
        base_url="https://litellm.example.invalid",
        transport=httpx.MockTransport(wrong_dimension),
    ) as client:
        gateway = LiteLLMGateway(
            "https://litellm.example.invalid",
            SecretStr("unit-test-key"),
            client=client,
        )
        with pytest.raises(ExternalServiceError) as caught:
            await gateway.embed(["測試"], model="bge-m3", expected_dimension=2)
    assert caught.value.category == "embedding_dimension_mismatch"

    response_marker = "private-upstream-response-marker"

    async def failed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=response_marker)

    async with httpx.AsyncClient(
        base_url="https://litellm.example.invalid",
        transport=httpx.MockTransport(failed),
    ) as client:
        gateway = LiteLLMGateway(
            "https://litellm.example.invalid",
            SecretStr("unit-test-key-marker"),
            client=client,
        )
        with pytest.raises(ExternalServiceError) as caught:
            await gateway.embed(["測試"], model="bge-m3", expected_dimension=2)
    assert caught.value.category == "http_error"
    assert "status=502" in str(caught.value)
    assert response_marker not in str(caught.value)
    assert "unit-test-key-marker" not in str(caught.value)


@pytest.mark.asyncio
async def test_qdrant_uses_query_api_and_round_trips_trusted_payloads() -> None:
    requests: list[tuple[str, str, dict[str, Any]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        requests.append((request.method, request.url.path, body))
        if request.method == "GET" and request.url.path == "/collections/baseline":
            return httpx.Response(404, json={"status": "not found"})
        if request.method == "PUT" and request.url.path == "/collections/baseline":
            return httpx.Response(200, json={"result": True})
        if request.url.path == "/collections/baseline/points/query":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "points": [
                            {
                                "id": 9,
                                "score": 0.875,
                                "payload": {
                                    "provision_id": 9,
                                    "embedding_input_hash": "a" * 64,
                                },
                            }
                        ]
                    }
                },
            )
        if request.method == "PUT" and request.url.path.endswith("/points"):
            return httpx.Response(200, json={"result": True})
        if request.method == "POST" and request.url.path.endswith("/points"):
            if body.get("with_vector"):
                return httpx.Response(
                    200,
                    json={"result": [{"id": 9, "vector": [1.0, 0.0]}]},
                )
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "id": 9,
                            "payload": {
                                "provision_id": 9,
                                "record_hash": "b" * 64,
                            },
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    async with httpx.AsyncClient(
        base_url="https://qdrant.example.invalid",
        transport=httpx.MockTransport(handler),
    ) as client:
        store = QdrantVectorStore(
            "https://qdrant.example.invalid",
            SecretStr("unit-test-key"),
            client=client,
        )
        await store.ensure_collection("baseline", dimension=2)
        await store.upsert(
            "baseline",
            [
                VectorPoint(
                    point_id=9,
                    vector=[1.0, 0.0],
                    payload={"provision_id": 9, "is_current": True},
                )
            ],
        )
        hits = await store.search("baseline", [1.0, 0.0], limit=6)
        payloads = await store.get_payloads("baseline", [9])
        scores = await store.scores_for_ids("baseline", [1.0, 0.0], [9])

    assert hits[0].point_id == 9
    assert hits[0].score == pytest.approx(0.875)
    assert hits[0].payload["embedding_input_hash"] == "a" * 64
    assert payloads[9]["record_hash"] == "b" * 64
    assert scores == {9: pytest.approx(1.0)}

    create_body = next(
        body
        for method, path, body in requests
        if method == "PUT" and path == "/collections/baseline"
    )
    assert create_body == {"vectors": {"size": 2, "distance": "Cosine"}}
    upsert_body = next(
        body
        for method, path, body in requests
        if method == "PUT" and path.endswith("/points")
    )
    assert upsert_body["points"][0]["payload"] == {
        "provision_id": 9,
        "is_current": True,
    }
    query_body = next(
        body for _method, path, body in requests if path.endswith("/points/query")
    )
    assert query_body == {
        "query": [1.0, 0.0],
        "filter": {"must": [{"key": "is_current", "match": {"value": True}}]},
        "limit": 6,
        "with_payload": True,
        "with_vector": False,
    }


@pytest.mark.asyncio
async def test_qdrant_collection_readiness_never_creates_a_missing_collection() -> None:
    methods: list[str] = []

    async def missing_collection(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        assert request.url.path == "/collections/baseline"
        return httpx.Response(404, json={"status": "not found"})

    async with httpx.AsyncClient(
        base_url="https://qdrant.example.invalid",
        transport=httpx.MockTransport(missing_collection),
    ) as client:
        store = QdrantVectorStore(
            "https://qdrant.example.invalid",
            SecretStr("unit-test-key"),
            client=client,
        )
        ready = await store.collection_is_ready("baseline", dimension=1_024)

    assert ready is False
    assert methods == ["GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_category", "expected_ready"),
    [
        (200, "ready", True),
        (302, "redirect", False),
        (401, "authentication_failed", False),
        (403, "authorization_failed", False),
        (404, "endpoint_not_found", False),
        (429, "rate_limited", False),
        (503, "upstream_error", False),
        (504, "timeout", False),
    ],
)
async def test_litellm_readiness_returns_only_allowlisted_status_categories(
    status_code: int,
    expected_category: str,
    expected_ready: bool,
) -> None:
    private_marker = "PRIVATE_RESPONSE_MARKER"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health/readiness"
        return httpx.Response(
            status_code,
            text=private_marker,
            headers={"x-private-marker": private_marker},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        gateway = LiteLLMGateway(
            "https://litellm.example.invalid",
            SecretStr("private-key-marker"),
            client=client,
        )
        result = await gateway.readiness_status()

    assert result.ready is expected_ready
    assert result.category == expected_category
    assert result.status_code == status_code
    assert private_marker not in repr(result)
    assert "litellm.example.invalid" not in repr(result)
    assert "private-key-marker" not in repr(result)


@pytest.mark.asyncio
async def test_readiness_transport_error_is_redacted() -> None:
    private_marker = "PRIVATE_TRANSPORT_MARKER"

    async def failed(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(private_marker, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(failed),
    ) as client:
        store = QdrantVectorStore(
            "https://qdrant.example.invalid",
            SecretStr("private-key-marker"),
            client=client,
        )
        result = await store.readiness_status()

    assert result.ready is False
    assert result.category == "connection_error"
    assert result.status_code is None
    assert private_marker not in repr(result)
    assert "qdrant.example.invalid" not in repr(result)
    assert "private-key-marker" not in repr(result)


@pytest.mark.asyncio
async def test_litellm_preserves_reverse_proxy_base_path() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/health/readiness"):
            return httpx.Response(200)
        if request.url.path.endswith("/v1/embeddings"):
            return httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]},
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        gateway = LiteLLMGateway(
            "https://gateway.example.invalid/services/litellm/",
            SecretStr("unit-test-key"),
            client=client,
        )
        assert await gateway.is_ready() is True
        await gateway.embed(["測試"], model="bge-m3", expected_dimension=2)

    assert paths == [
        "/services/litellm/health/readiness",
        "/services/litellm/v1/embeddings",
    ]


@pytest.mark.asyncio
async def test_qdrant_preserves_reverse_proxy_base_path() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/readyz"):
            return httpx.Response(200)
        if request.url.path.endswith("/collections/baseline"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "config": {
                            "params": {"vectors": {"size": 1_024, "distance": "Cosine"}}
                        }
                    }
                },
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        store = QdrantVectorStore(
            "https://gateway.example.invalid/services/qdrant/",
            SecretStr("unit-test-key"),
            client=client,
        )
        assert await store.is_ready() is True
        assert await store.collection_is_ready("baseline", dimension=1_024) is True

    assert paths == [
        "/services/qdrant/readyz",
        "/services/qdrant/collections/baseline",
    ]
