"""Minimal Qdrant HTTP adapter with explicit payload and dimension checks."""

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
from legal_qa_platform.ports.vector_store import VectorHit, VectorPoint


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ExternalServiceError("qdrant", "vector_dimension_mismatch")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


class QdrantVectorStore:
    """Qdrant implementation using stable provision IDs as point IDs."""

    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        *,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            headers={
                "api-key": api_key.get_secret_value(),
                "Content-Type": "application/json",
            },
        )

    def _url(self, path: str) -> str:
        """Join an API path without discarding a reverse-proxy base prefix."""

        return f"{self._base_url}/{path.lstrip('/')}"

    async def __aenter__(self) -> QdrantVectorStore:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _json_request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        try:
            response = await self._client.request(
                method,
                self._url(path),
                json=body,
            )
            require_success("qdrant", response)
            payload = response.json()
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise external_http_error("qdrant", exc) from None
        if not isinstance(payload, Mapping):
            raise ExternalServiceError("qdrant", "invalid_response")
        return payload

    async def _collection_config(self, name: str) -> tuple[int, str] | None:
        try:
            response = await self._client.get(self._url(f"collections/{name}"))
        except Exception as exc:
            raise external_http_error("qdrant", exc) from None
        if response.status_code == 404:
            return None
        require_success("qdrant", response)
        try:
            payload = response.json()
            result = payload["result"]
            vectors = result["config"]["params"]["vectors"]
            actual_dimension = vectors["size"]
            actual_distance = vectors["distance"]
        except (KeyError, TypeError, ValueError):
            raise ExternalServiceError("qdrant", "invalid_collection_config") from None
        if not isinstance(actual_dimension, int) or not isinstance(
            actual_distance, str
        ):
            raise ExternalServiceError("qdrant", "invalid_collection_config")
        return actual_dimension, actual_distance

    async def collection_is_ready(
        self,
        name: str,
        *,
        dimension: int,
        distance: str = "Cosine",
    ) -> bool:
        """Check the collection contract without creating or changing it."""

        try:
            config = await self._collection_config(name)
        except ExternalServiceError:
            return False
        return bool(
            config is not None
            and config[0] == dimension
            and config[1].casefold() == distance.casefold()
        )

    async def ensure_collection(
        self,
        name: str,
        *,
        dimension: int,
        distance: str = "Cosine",
    ) -> None:
        if (
            isinstance(dimension, bool)
            or not isinstance(dimension, int)
            or dimension <= 0
        ):
            raise ValueError("dimension must be positive")
        config = await self._collection_config(name)
        if config is None:
            await self._json_request(
                "PUT",
                f"/collections/{name}",
                body={"vectors": {"size": dimension, "distance": distance}},
            )
            return
        actual_dimension, actual_distance = config
        if (
            actual_dimension != dimension
            or str(actual_distance).casefold() != distance.casefold()
        ):
            raise ExternalServiceError(
                "qdrant",
                "collection_config_mismatch",
                "dimension_or_distance",
            )

    async def upsert(self, collection: str, points: Sequence[VectorPoint]) -> None:
        if not points:
            return
        await self._json_request(
            "PUT",
            f"/collections/{collection}/points?wait=true",
            body={
                "points": [
                    {
                        "id": point.point_id,
                        "vector": list(point.vector),
                        "payload": dict(point.payload),
                    }
                    for point in points
                ]
            },
        )

    async def search(
        self,
        collection: str,
        query_vector: Sequence[float],
        *,
        limit: int,
    ) -> list[VectorHit]:
        payload = await self._json_request(
            "POST",
            f"/collections/{collection}/points/query",
            body={
                "query": list(query_vector),
                "filter": {"must": [{"key": "is_current", "match": {"value": True}}]},
                "limit": limit,
                "with_payload": True,
                "with_vector": False,
            },
        )
        result = payload.get("result")
        raw_points = result.get("points") if isinstance(result, Mapping) else result
        if not isinstance(raw_points, list):
            raise ExternalServiceError("qdrant", "invalid_query_result")
        hits: list[VectorHit] = []
        for item in raw_points:
            if not isinstance(item, Mapping):
                raise ExternalServiceError("qdrant", "invalid_query_point")
            point_id = item.get("id")
            score = item.get("score")
            point_payload = item.get("payload", {})
            if (
                isinstance(point_id, bool)
                or not isinstance(point_id, int)
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(float(score))
                or not isinstance(point_payload, Mapping)
            ):
                raise ExternalServiceError("qdrant", "invalid_query_point")
            hits.append(
                VectorHit(
                    point_id=point_id,
                    score=float(score),
                    payload=dict(point_payload),
                )
            )
        return hits

    async def scores_for_ids(
        self,
        collection: str,
        query_vector: Sequence[float],
        provision_ids: Sequence[int],
    ) -> Mapping[int, float]:
        if not provision_ids:
            return {}
        payload = await self._json_request(
            "POST",
            f"/collections/{collection}/points",
            body={
                "ids": list(dict.fromkeys(provision_ids)),
                "with_payload": False,
                "with_vector": True,
            },
        )
        raw_points = payload.get("result")
        if not isinstance(raw_points, list):
            raise ExternalServiceError("qdrant", "invalid_retrieve_result")
        scores: dict[int, float] = {}
        for item in raw_points:
            point_id = item.get("id") if isinstance(item, Mapping) else None
            if (
                not isinstance(item, Mapping)
                or isinstance(point_id, bool)
                or not isinstance(point_id, int)
            ):
                raise ExternalServiceError("qdrant", "invalid_retrieved_point")
            raw_vector = item.get("vector")
            if isinstance(raw_vector, Mapping):
                # This baseline uses one unnamed dense vector; named vectors are
                # rejected instead of choosing one implicitly.
                raise ExternalServiceError("qdrant", "unexpected_named_vector")
            if not isinstance(raw_vector, list):
                raise ExternalServiceError("qdrant", "missing_retrieved_vector")
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in raw_vector
            ):
                raise ExternalServiceError("qdrant", "invalid_retrieved_vector")
            try:
                vector = [float(value) for value in raw_vector]
            except (TypeError, ValueError):
                raise ExternalServiceError(
                    "qdrant", "invalid_retrieved_vector"
                ) from None
            scores[point_id] = _cosine(query_vector, vector)
        return scores

    async def get_payloads(
        self,
        collection: str,
        provision_ids: Sequence[int],
    ) -> Mapping[int, Mapping[str, Any]]:
        if not provision_ids:
            return {}
        payload = await self._json_request(
            "POST",
            f"/collections/{collection}/points",
            body={
                "ids": list(dict.fromkeys(provision_ids)),
                "with_payload": True,
                "with_vector": False,
            },
        )
        raw_points = payload.get("result")
        if not isinstance(raw_points, list):
            raise ExternalServiceError("qdrant", "invalid_retrieve_result")
        result: dict[int, Mapping[str, Any]] = {}
        for item in raw_points:
            point_id = item.get("id") if isinstance(item, Mapping) else None
            if (
                not isinstance(item, Mapping)
                or isinstance(point_id, bool)
                or not isinstance(point_id, int)
            ):
                raise ExternalServiceError("qdrant", "invalid_retrieved_point")
            point_payload = item.get("payload")
            if not isinstance(point_payload, Mapping):
                raise ExternalServiceError("qdrant", "missing_retrieved_payload")
            result[point_id] = dict(point_payload)
        return result

    async def delete(self, collection: str, provision_ids: Sequence[int]) -> None:
        if not provision_ids:
            return
        await self._json_request(
            "POST",
            f"/collections/{collection}/points/delete?wait=true",
            body={"points": list(dict.fromkeys(provision_ids))},
        )

    async def set_payload(
        self,
        collection: str,
        provision_ids: Sequence[int],
        payload: Mapping[str, Any],
    ) -> None:
        if not provision_ids:
            return
        await self._json_request(
            "POST",
            f"/collections/{collection}/points/payload?wait=true",
            body={
                "payload": dict(payload),
                "points": list(dict.fromkeys(provision_ids)),
            },
        )

    async def is_ready(self) -> bool:
        return (await self.readiness_status()).ready

    async def readiness_status(self) -> HttpReadinessResult:
        """Return a redacted, allowlisted readiness result for diagnostics."""

        return await probe_http_readiness(
            self._client,
            self._url("readyz"),
        )
