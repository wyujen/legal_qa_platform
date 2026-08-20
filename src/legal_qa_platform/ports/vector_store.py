"""Vector-store contract owned by the application, not a vendor SDK."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class VectorPoint:
    point_id: int
    vector: Sequence[float]
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class VectorHit:
    point_id: int
    score: float
    payload: Mapping[str, Any]


class VectorStore(Protocol):
    async def collection_is_ready(
        self,
        name: str,
        *,
        dimension: int,
        distance: str = "Cosine",
    ) -> bool: ...

    async def ensure_collection(
        self,
        name: str,
        *,
        dimension: int,
        distance: str = "Cosine",
    ) -> None: ...

    async def upsert(self, collection: str, points: Sequence[VectorPoint]) -> None: ...

    async def search(
        self,
        collection: str,
        query_vector: Sequence[float],
        *,
        limit: int,
    ) -> list[VectorHit]: ...

    async def scores_for_ids(
        self,
        collection: str,
        query_vector: Sequence[float],
        provision_ids: Sequence[int],
    ) -> Mapping[int, float]: ...

    async def get_payloads(
        self,
        collection: str,
        provision_ids: Sequence[int],
    ) -> Mapping[int, Mapping[str, Any]]: ...

    async def set_payload(
        self,
        collection: str,
        provision_ids: Sequence[int],
        payload: Mapping[str, Any],
    ) -> None: ...

    async def delete(self, collection: str, provision_ids: Sequence[int]) -> None: ...

    async def is_ready(self) -> bool: ...
