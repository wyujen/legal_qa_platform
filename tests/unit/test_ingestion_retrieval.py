from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import pytest

from legal_qa_platform.domain.legal import LegalProvision
from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.errors import ExternalServiceError
from legal_qa_platform.ports.repositories import (
    ProvisionSnapshot,
    ProvisionSyncState,
    ProvisionWrite,
    PublishSummary,
    SyncRun,
)
from legal_qa_platform.ports.vector_store import VectorHit, VectorPoint
from legal_qa_platform.services.ingestion import IngestionService, prepare_provision
from legal_qa_platform.services.retrieval import RetrievalService


def make_provision(
    provision_id: int = 9,
    *,
    content: str = "申請人應於七日內提出文件。",
    sort_order: int = 1,
) -> LegalProvision:
    return LegalProvision(
        provision_id=provision_id,
        document_name="測試法規",
        article_no=f"第{provision_id}條",
        title="申請期限",
        content=content,
        search_text=f"測試法規 第{provision_id}條 申請期限 {content}",
        sort_order=sort_order,
    )


def make_profile() -> RagProfile:
    return RagProfile(
        embedding_dimension=2,
        candidate_k=3,
        top_k=3,
        min_score=0.0,
    )


def make_sync_state(
    provision: LegalProvision,
    profile: RagProfile,
    *,
    generation: int = 4,
) -> ProvisionSyncState:
    prepared = prepare_provision(provision)
    return ProvisionSyncState(
        provision_id=provision.provision_id,
        canonical_stable_key=prepared.canonical_stable_key,
        document_name=provision.document_name,
        article_no=provision.article_no,
        paragraph_no=provision.paragraph_no,
        subparagraph_no=provision.subparagraph_no,
        identity_status="current",
        record_hash=prepared.record_hash,
        embedding_input_hash=prepared.embedding_input_hash,
        embedding_model=profile.embedding_model,
        vector_collection=profile.vector_collection,
        vector_generation=generation,
        is_current=True,
    )


def make_payload(
    provision: LegalProvision,
    profile: RagProfile,
    *,
    generation: int = 4,
) -> dict[str, object]:
    prepared = prepare_provision(provision)
    return {
        "provision_id": provision.provision_id,
        "document_name": provision.document_name,
        "article_no": provision.article_no,
        "official_content_hash": prepared.official_content_hash,
        "record_hash": prepared.record_hash,
        "embedding_input_hash": prepared.embedding_input_hash,
        "embedding_model": profile.embedding_model,
        "vector_generation": generation,
        "is_current": True,
    }


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str, int]] = []

    async def embed(
        self,
        texts: Sequence[str],
        *,
        model: str,
        expected_dimension: int,
    ) -> list[list[float]]:
        self.calls.append((tuple(texts), model, expected_dimension))
        return [[1.0, *([0.0] * (expected_dimension - 1))] for _ in texts]


class FakeIngestionRepository:
    def __init__(
        self,
        *,
        states: Mapping[int, ProvisionSyncState] | None = None,
        deactivated_ids: tuple[int, ...] = (),
    ) -> None:
        self.states = dict(states or {})
        self.deactivated_ids = deactivated_ids
        self.run = SyncRun(
            run_id=UUID("00000000-0000-0000-0000-000000000007"),
            generation=7,
        )
        self.started: dict[str, object] | None = None
        self.staged: tuple[int, int] | None = None
        self.published_writes: tuple[ProvisionWrite, ...] = ()
        self.full_snapshot: bool | None = None
        self.failed: list[str] = []

    async def start_collection_run(self, **values: object) -> SyncRun:
        self.started = dict(values)
        return self.run

    async def mark_vectors_staged(
        self,
        _run_id: UUID,
        *,
        embedded_count: int,
        reused_vector_count: int,
    ) -> None:
        self.staged = (embedded_count, reused_vector_count)

    async def mark_run_failed(self, _run_id: UUID, category: str) -> None:
        self.failed.append(category)

    async def get_sync_states(
        self, provision_ids: Sequence[int]
    ) -> dict[int, ProvisionSyncState]:
        return {
            provision_id: self.states[provision_id]
            for provision_id in provision_ids
            if provision_id in self.states
        }

    async def get_max_provision_id(self) -> int:
        return max(self.states, default=8)

    async def publish_snapshot(
        self,
        _run: SyncRun,
        writes: Sequence[ProvisionWrite],
        *,
        full_snapshot: bool,
    ) -> PublishSummary:
        self.published_writes = tuple(writes)
        self.full_snapshot = full_snapshot
        return PublishSummary(
            provision_count=len(writes),
            deactivated_ids=self.deactivated_ids if full_snapshot else (),
        )


class FakeIngestionVectorStore:
    def __init__(self, payloads: Mapping[int, Mapping[str, Any]] | None = None) -> None:
        self.payloads = {key: dict(value) for key, value in (payloads or {}).items()}
        self.ensured: tuple[str, int, str] | None = None
        self.upserted: list[VectorPoint] = []
        self.set_payload_calls: list[tuple[str, tuple[int, ...], dict[str, Any]]] = []

    async def collection_is_ready(
        self,
        _name: str,
        *,
        dimension: int,
        distance: str = "Cosine",
    ) -> bool:
        del dimension, distance
        return True

    async def ensure_collection(
        self,
        name: str,
        *,
        dimension: int,
        distance: str = "Cosine",
    ) -> None:
        self.ensured = (name, dimension, distance)

    async def upsert(self, _collection: str, points: Sequence[VectorPoint]) -> None:
        self.upserted.extend(points)
        for point in points:
            self.payloads[point.point_id] = dict(point.payload)

    async def get_payloads(
        self,
        _collection: str,
        provision_ids: Sequence[int],
    ) -> Mapping[int, Mapping[str, Any]]:
        return {
            provision_id: self.payloads[provision_id]
            for provision_id in provision_ids
            if provision_id in self.payloads
        }

    async def set_payload(
        self,
        collection: str,
        provision_ids: Sequence[int],
        payload: Mapping[str, Any],
    ) -> None:
        self.set_payload_calls.append((collection, tuple(provision_ids), dict(payload)))
        for provision_id in provision_ids:
            self.payloads.setdefault(provision_id, {}).update(payload)

    async def delete(self, _collection: str, _provision_ids: Sequence[int]) -> None:
        return None

    async def search(
        self,
        _collection: str,
        _query_vector: Sequence[float],
        *,
        limit: int,
    ) -> list[VectorHit]:
        del limit
        return []

    async def scores_for_ids(
        self,
        _collection: str,
        _query_vector: Sequence[float],
        _provision_ids: Sequence[int],
    ) -> Mapping[int, float]:
        return {}

    async def is_ready(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_full_snapshot_embeds_hashes_publishes_and_deactivates() -> None:
    profile = make_profile()
    provision = make_provision()
    prepared = prepare_provision(provision)
    repository = FakeIngestionRepository(deactivated_ids=(99,))
    vectors = FakeIngestionVectorStore()
    embeddings = FakeEmbeddingProvider()
    service = IngestionService(
        repository=repository,
        vector_store=vectors,
        embeddings=embeddings,
        profile=profile,
    )

    summary = await service.sync([provision], mode="full_snapshot")

    assert summary.embedded_count == 1
    assert summary.reused_vector_count == 0
    assert summary.deactivated_count == 1
    assert repository.full_snapshot is True
    assert repository.staged == (1, 0)
    write = repository.published_writes[0]
    assert write.official_content_hash == prepared.official_content_hash
    assert write.record_hash == prepared.record_hash
    assert write.embedding_input_hash == prepared.embedding_input_hash
    assert write.vector_generation == 7
    assert write.vector_action == "upserted"
    assert vectors.upserted[0].payload["embedding_input_hash"] == (
        prepared.embedding_input_hash
    )
    assert vectors.set_payload_calls[-1][1:] == ((99,), {"is_current": False})


@pytest.mark.asyncio
async def test_partial_sync_reuses_unchanged_vector_without_deactivation() -> None:
    profile = make_profile()
    provision = make_provision()
    state = make_sync_state(provision, profile)
    repository = FakeIngestionRepository(
        states={provision.provision_id: state},
        deactivated_ids=(99,),
    )
    vectors = FakeIngestionVectorStore(
        {provision.provision_id: make_payload(provision, profile)}
    )
    embeddings = FakeEmbeddingProvider()
    service = IngestionService(
        repository=repository,
        vector_store=vectors,
        embeddings=embeddings,
        profile=profile,
    )

    summary = await service.sync([provision], mode="partial")

    assert summary.embedded_count == 0
    assert summary.reused_vector_count == 1
    assert summary.deactivated_count == 0
    assert embeddings.calls == []
    assert vectors.upserted == []
    assert vectors.set_payload_calls == []
    assert repository.full_snapshot is False
    assert repository.published_writes[0].vector_action == "reused"
    assert repository.published_writes[0].vector_generation == 4


@pytest.mark.asyncio
async def test_changed_embedding_hash_forces_new_vector() -> None:
    profile = make_profile()
    old = make_provision(content="舊的法規文字。")
    changed = make_provision(content="新的法規文字及申請期限。")
    repository = FakeIngestionRepository(
        states={old.provision_id: make_sync_state(old, profile)}
    )
    vectors = FakeIngestionVectorStore({old.provision_id: make_payload(old, profile)})
    embeddings = FakeEmbeddingProvider()
    service = IngestionService(
        repository=repository,
        vector_store=vectors,
        embeddings=embeddings,
        profile=profile,
    )

    summary = await service.sync([changed], mode="partial")

    assert summary.embedded_count == 1
    assert len(embeddings.calls) == 1
    assert repository.published_writes[0].embedding_input_hash == (
        prepare_provision(changed).embedding_input_hash
    )
    assert repository.published_writes[0].embedding_input_hash != (
        prepare_provision(old).embedding_input_hash
    )


def make_snapshot(
    provision: LegalProvision,
    profile: RagProfile,
    *,
    generation: int = 4,
) -> ProvisionSnapshot:
    prepared = prepare_provision(provision)
    return ProvisionSnapshot(
        provision=provision,
        official_content_hash=prepared.official_content_hash,
        record_hash=prepared.record_hash,
        embedding_input_hash=prepared.embedding_input_hash,
        embedding_model=profile.embedding_model,
        vector_collection=profile.vector_collection,
        vector_generation=generation,
    )


class FakeLegalRepository:
    def __init__(
        self,
        snapshots: Mapping[int, ProvisionSnapshot],
        keyword: Sequence[ProvisionSnapshot],
    ) -> None:
        self.snapshots = dict(snapshots)
        self.keyword = list(keyword)

    async def get_provisions_by_ids(
        self, provision_ids: Sequence[int]
    ) -> dict[int, ProvisionSnapshot]:
        return {
            provision_id: self.snapshots[provision_id]
            for provision_id in provision_ids
            if provision_id in self.snapshots
        }

    async def keyword_candidates(
        self,
        *,
        compact_query: str,
        terms: Sequence[str],
        limit: int,
    ) -> list[ProvisionSnapshot]:
        del compact_query, terms
        return self.keyword[:limit]


class FakeRetrievalVectorStore:
    def __init__(
        self,
        *,
        hits: Sequence[VectorHit],
        payloads: Mapping[int, Mapping[str, Any]],
        supplemental_scores: Mapping[int, float],
    ) -> None:
        self.hits = list(hits)
        self.payloads = dict(payloads)
        self.supplemental_scores = dict(supplemental_scores)
        self.search_limit: int | None = None
        self.payload_ids: tuple[int, ...] = ()
        self.score_ids: tuple[int, ...] = ()

    async def collection_is_ready(
        self,
        _name: str,
        *,
        dimension: int,
        distance: str = "Cosine",
    ) -> bool:
        del dimension, distance
        return True

    async def ensure_collection(
        self,
        _name: str,
        *,
        dimension: int,
        distance: str = "Cosine",
    ) -> None:
        del dimension, distance

    async def upsert(self, _collection: str, _points: Sequence[VectorPoint]) -> None:
        return None

    async def search(
        self,
        _collection: str,
        _query_vector: Sequence[float],
        *,
        limit: int,
    ) -> list[VectorHit]:
        self.search_limit = limit
        return self.hits

    async def get_payloads(
        self,
        _collection: str,
        provision_ids: Sequence[int],
    ) -> Mapping[int, Mapping[str, Any]]:
        self.payload_ids = tuple(provision_ids)
        return {
            provision_id: self.payloads[provision_id]
            for provision_id in provision_ids
            if provision_id in self.payloads
        }

    async def scores_for_ids(
        self,
        _collection: str,
        _query_vector: Sequence[float],
        provision_ids: Sequence[int],
    ) -> Mapping[int, float]:
        self.score_ids = tuple(provision_ids)
        return {
            provision_id: self.supplemental_scores[provision_id]
            for provision_id in provision_ids
            if provision_id in self.supplemental_scores
        }

    async def set_payload(
        self,
        _collection: str,
        _provision_ids: Sequence[int],
        _payload: Mapping[str, Any],
    ) -> None:
        return None

    async def delete(self, _collection: str, _provision_ids: Sequence[int]) -> None:
        return None

    async def is_ready(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_retrieval_drops_stale_hits_and_scores_full_candidate_union() -> None:
    profile = RagProfile(
        embedding_dimension=2,
        candidate_k=2,
        top_k=2,
        min_score=0.0,
    )
    stale = make_snapshot(make_provision(9, content="舊候選"), profile)
    vector = make_snapshot(make_provision(10, content="其他現行規定"), profile)
    keyword = make_snapshot(
        make_provision(11, content="申請期限應於七日內完成"), profile
    )
    repository = FakeLegalRepository(
        {9: stale, 10: vector, 11: keyword},
        [keyword],
    )
    vectors = FakeRetrievalVectorStore(
        hits=[
            VectorHit(
                point_id=9,
                score=0.99,
                payload={
                    **make_payload(stale.provision, profile),
                    "vector_generation": 3,
                },
            ),
            VectorHit(
                point_id=10,
                score=0.8,
                payload=make_payload(vector.provision, profile),
            ),
        ],
        payloads={11: make_payload(keyword.provision, profile)},
        supplemental_scores={11: 0.7},
    )
    embeddings = FakeEmbeddingProvider()
    service = RetrievalService(
        repository=repository,
        vector_store=vectors,
        embeddings=embeddings,
        profile=profile,
    )

    results = await service.retrieve("申請期限")

    assert {item.provision_id for item in results} == {10, 11}
    assert 9 not in {item.provision_id for item in results}
    keyword_result = next(item for item in results if item.provision_id == 11)
    assert keyword_result.vector_score == pytest.approx(0.7)
    assert vectors.search_limit == 4
    assert vectors.payload_ids == (11,)
    assert vectors.score_ids == (11,)


@pytest.mark.asyncio
async def test_retrieval_rejects_stale_keyword_only_vector() -> None:
    profile = RagProfile(
        embedding_dimension=2,
        candidate_k=1,
        top_k=1,
        min_score=0.0,
    )
    keyword = make_snapshot(make_provision(11), profile)
    repository = FakeLegalRepository({11: keyword}, [keyword])
    stale_payload = make_payload(keyword.provision, profile)
    stale_payload["embedding_input_hash"] = "0" * 64
    vectors = FakeRetrievalVectorStore(
        hits=[],
        payloads={11: stale_payload},
        supplemental_scores={11: 0.7},
    )
    service = RetrievalService(
        repository=repository,
        vector_store=vectors,
        embeddings=FakeEmbeddingProvider(),
        profile=profile,
    )

    with pytest.raises(ExternalServiceError) as caught:
        await service.retrieve("申請期限")
    assert caught.value.category == "missing_or_stale_candidate_vectors"
    assert caught.value.detail == "count=1"
