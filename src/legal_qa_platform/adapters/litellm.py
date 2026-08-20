"""OpenAI-compatible LiteLLM REST adapter for chat and embeddings."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from legal_qa_platform.adapters.http_safety import (
    HttpReadinessResult,
    external_http_error,
    probe_http_readiness,
    require_success,
)
from legal_qa_platform.errors import ExternalServiceError
from legal_qa_platform.ports.models import ChatCompletion, ChatMessage


class LiteLLMGateway:
    """Call only the documented LiteLLM REST boundary.

    The adapter owns HTTP and credential handling. It deliberately does not read
    environment variables and never includes response bodies in exceptions.
    """

    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        *,
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            trust_env=False,
            headers={
                "Authorization": f"Bearer {api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
        )

    def _url(self, path: str) -> str:
        """Join an API path without discarding a reverse-proxy base prefix."""

        return f"{self._base_url}/{path.lstrip('/')}"

    async def __aenter__(self) -> LiteLLMGateway:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def embed(
        self,
        texts: Sequence[str],
        *,
        model: str,
        expected_dimension: int,
    ) -> list[list[float]]:
        if (
            isinstance(expected_dimension, bool)
            or not isinstance(expected_dimension, int)
            or expected_dimension <= 0
        ):
            raise ValueError("expected_dimension must be a positive integer.")
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Embedding input must contain non-empty strings.")

        try:
            response = await self._client.post(
                self._url("v1/embeddings"),
                json={"model": model, "input": list(texts)},
            )
            require_success("litellm", response)
            payload = response.json()
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise external_http_error("litellm", exc) from None

        data = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(data, list) or len(data) != len(texts):
            raise ExternalServiceError("litellm", "invalid_embedding_count")

        ordered: list[tuple[int, list[float]]] = []
        for fallback_index, item in enumerate(data):
            if not isinstance(item, Mapping):
                raise ExternalServiceError("litellm", "invalid_embedding_item")
            raw_vector = item.get("embedding")
            if not isinstance(raw_vector, list):
                raise ExternalServiceError("litellm", "invalid_embedding_vector")
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in raw_vector
            ):
                raise ExternalServiceError("litellm", "invalid_embedding_vector")
            try:
                vector = [float(value) for value in raw_vector]
            except (TypeError, ValueError):
                raise ExternalServiceError(
                    "litellm", "invalid_embedding_vector"
                ) from None
            if len(vector) != expected_dimension:
                raise ExternalServiceError(
                    "litellm",
                    "embedding_dimension_mismatch",
                    f"expected={expected_dimension} actual={len(vector)}",
                )
            if not all(math.isfinite(value) for value in vector):
                raise ExternalServiceError("litellm", "non_finite_embedding")
            index = item.get("index", fallback_index)
            if isinstance(index, bool) or not isinstance(index, int):
                raise ExternalServiceError("litellm", "invalid_embedding_index")
            ordered.append((index, vector))

        ordered.sort(key=lambda pair: pair[0])
        if [index for index, _ in ordered] != list(range(len(texts))):
            raise ExternalServiceError("litellm", "invalid_embedding_indexes")
        return [vector for _, vector in ordered]

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        max_tokens: int,
        response_schema: Mapping[str, Any],
    ) -> ChatCompletion:
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens <= 0
        ):
            raise ValueError("max_tokens must be positive.")
        if not messages:
            raise ValueError("At least one chat message is required.")

        body = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            # Required by the deployed campus-qa backend.
            "max_tokens": max_tokens,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "legal_qa_answer",
                    "strict": True,
                    "schema": dict(response_schema),
                },
            },
        }
        try:
            response = await self._client.post(
                self._url("v1/chat/completions"),
                json=body,
            )
            require_success("litellm", response)
            payload = response.json()
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise external_http_error("litellm", exc) from None

        if not isinstance(payload, Mapping):
            raise ExternalServiceError("litellm", "invalid_chat_response")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ExternalServiceError("litellm", "missing_chat_choice")
        first = choices[0]
        message = first.get("message") if isinstance(first, Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str) or not content.strip():
            raise ExternalServiceError("litellm", "empty_chat_content")

        usage_payload = payload.get("usage")
        usage: dict[str, int] | None = None
        if isinstance(usage_payload, Mapping):
            usage = {
                str(key): int(value)
                for key, value in usage_payload.items()
                if isinstance(value, int) and not isinstance(value, bool)
            }
        response_model = payload.get("model")
        response_id = payload.get("id")
        return ChatCompletion(
            content=content,
            model=response_model if isinstance(response_model, str) else model,
            request_id=response_id if isinstance(response_id, str) else None,
            usage=usage,
        )

    async def is_ready(self) -> bool:
        return (await self.readiness_status()).ready

    async def readiness_status(self) -> HttpReadinessResult:
        """Return a redacted, allowlisted readiness result for diagnostics."""

        return await probe_http_readiness(
            self._client,
            self._url("health/readiness"),
        )
