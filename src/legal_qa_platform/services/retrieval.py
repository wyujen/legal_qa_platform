"""Qdrant + PostgreSQL candidate union and deterministic hybrid retrieval."""

from __future__ import annotations

from contextlib import nullcontext
from time import perf_counter
from typing import Any

from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.domain.retrieval import RetrievalCandidate, RetrievalResult
from legal_qa_platform.errors import ExternalServiceError
from legal_qa_platform.ports.models import EmbeddingProvider
from legal_qa_platform.ports.observability import Trace
from legal_qa_platform.ports.repositories import LegalRepository, ProvisionSnapshot
from legal_qa_platform.ports.vector_store import VectorHit, VectorStore
from legal_qa_platform.services.normalization import (
    compact_keyword_text,
    extract_keyword_terms,
    keyword_score,
    provision_search_text,
)
from legal_qa_platform.services.ranking import rank_candidate_union


def _payload_matches_snapshot(
    hit_payload: object,
    snapshot: ProvisionSnapshot,
    profile: RagProfile,
) -> bool:
    if not isinstance(hit_payload, dict):
        return False
    return bool(
        hit_payload.get("provision_id") == snapshot.provision.provision_id
        and hit_payload.get("embedding_input_hash") == snapshot.embedding_input_hash
        and hit_payload.get("embedding_model") == profile.embedding_model
        and hit_payload.get("vector_generation") == snapshot.vector_generation
        and snapshot.embedding_model == profile.embedding_model
        and snapshot.vector_collection == profile.vector_collection
    )


class RetrievalService:
    """Retrieve a trusted immutable Top K from two replaceable candidate stores."""

    def __init__(
        self,
        *,
        repository: LegalRepository,
        vector_store: VectorStore,
        embeddings: EmbeddingProvider,
        profile: RagProfile,
    ) -> None:
        self._repository = repository
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._profile = profile

    async def retrieve(
        self,
        normalized_question: str,
        *,
        trace: Trace | None = None,
        stage_latencies_ms: dict[str, float] | None = None,
    ) -> list[RetrievalResult]:
        question = normalized_question.strip()
        if not question:
            return []
        started = perf_counter()
        manager: Any = (
            trace.span(
                "embedding",
                metadata={"model": self._profile.embedding_model},
            )
            if trace
            else nullcontext(None)
        )
        with manager as span:
            vectors = await self._embeddings.embed(
                [question],
                model=self._profile.embedding_model,
                expected_dimension=self._profile.embedding_dimension,
            )
            if span:
                span.annotate(metadata={"dimension": len(vectors[0]) if vectors else 0})
        if stage_latencies_ms is not None:
            stage_latencies_ms["embedding"] = (perf_counter() - started) * 1000
        if len(vectors) != 1:
            raise ExternalServiceError("litellm", "invalid_query_embedding_count")
        query_vector = vectors[0]

        # Oversampling prevents a small number of orphan/stale Qdrant points from
        # consuming the complete candidate budget before PostgreSQL revalidation.
        started = perf_counter()
        manager = (
            trace.span(
                "vector_retrieval",
                metadata={
                    "collection": self._profile.vector_collection,
                    "candidate_k": self._profile.candidate_k,
                },
            )
            if trace
            else nullcontext(None)
        )
        with manager as span:
            raw_vector_hits = await self._vector_store.search(
                self._profile.vector_collection,
                query_vector,
                limit=self._profile.candidate_k * 2,
            )
            vector_snapshots = await self._repository.get_provisions_by_ids(
                [hit.point_id for hit in raw_vector_hits]
            )
            valid_vector_hits: list[VectorHit] = []
            for hit in raw_vector_hits:
                snapshot = vector_snapshots.get(hit.point_id)
                if snapshot is None:
                    continue
                if not _payload_matches_snapshot(hit.payload, snapshot, self._profile):
                    continue
                valid_vector_hits.append(hit)
                if len(valid_vector_hits) >= self._profile.candidate_k:
                    break
            if span:
                span.annotate(
                    metadata={
                        "raw_count": len(raw_vector_hits),
                        "trusted_count": len(valid_vector_hits),
                        "provision_ids": [hit.point_id for hit in valid_vector_hits],
                    }
                )
        if stage_latencies_ms is not None:
            stage_latencies_ms["vector_retrieval"] = (perf_counter() - started) * 1000

        started = perf_counter()
        manager = (
            trace.span(
                "keyword_retrieval",
                metadata={"candidate_k": self._profile.candidate_k},
            )
            if trace
            else nullcontext(None)
        )
        with manager as span:
            terms = sorted(extract_keyword_terms(question))
            keyword_snapshots = await self._repository.keyword_candidates(
                compact_query=compact_keyword_text(question),
                terms=terms,
                limit=self._profile.candidate_k,
            )
            if span:
                span.annotate(
                    metadata={
                        "term_count": len(terms),
                        "candidate_count": len(keyword_snapshots),
                        "provision_ids": [
                            item.provision.provision_id for item in keyword_snapshots
                        ],
                    }
                )
        if stage_latencies_ms is not None:
            stage_latencies_ms["keyword_retrieval"] = (perf_counter() - started) * 1000
        all_snapshots = dict(vector_snapshots)
        all_snapshots.update(
            {
                snapshot.provision.provision_id: snapshot
                for snapshot in keyword_snapshots
            }
        )

        vector_scores = {hit.point_id: hit.score for hit in valid_vector_hits}
        keyword_only_ids = [
            snapshot.provision.provision_id
            for snapshot in keyword_snapshots
            if snapshot.provision.provision_id not in vector_scores
        ]
        if keyword_only_ids:
            payloads = await self._vector_store.get_payloads(
                self._profile.vector_collection,
                keyword_only_ids,
            )
            invalid = [
                provision_id
                for provision_id in keyword_only_ids
                if provision_id not in payloads
                or not _payload_matches_snapshot(
                    payloads[provision_id],
                    all_snapshots[provision_id],
                    self._profile,
                )
            ]
            if invalid:
                raise ExternalServiceError(
                    "qdrant",
                    "missing_or_stale_candidate_vectors",
                    f"count={len(invalid)}",
                )
            supplemental_scores = await self._vector_store.scores_for_ids(
                self._profile.vector_collection,
                query_vector,
                keyword_only_ids,
            )
            if set(supplemental_scores) != set(keyword_only_ids):
                raise ExternalServiceError(
                    "qdrant",
                    "missing_candidate_vector_scores",
                    f"expected={len(keyword_only_ids)} "
                    f"actual={len(supplemental_scores)}",
                )
            vector_scores.update(supplemental_scores)

        vector_candidates = [
            RetrievalCandidate(provision_id=hit.point_id, score=hit.score)
            for hit in valid_vector_hits
        ]
        keyword_candidates = [
            RetrievalCandidate(
                provision_id=snapshot.provision.provision_id,
                score=keyword_score(
                    question,
                    provision_search_text(snapshot.provision),
                ),
            )
            for snapshot in keyword_snapshots
        ]
        started = perf_counter()
        manager = (
            trace.span(
                "hybrid_ranking",
                metadata={
                    "vector_weight": self._profile.vector_weight,
                    "keyword_weight": self._profile.keyword_weight,
                    "min_score": self._profile.min_score,
                    "top_k": self._profile.top_k,
                },
            )
            if trace
            else nullcontext(None)
        )
        with manager as span:
            results = rank_candidate_union(
                question,
                provisions={
                    identifier: snapshot.provision
                    for identifier, snapshot in all_snapshots.items()
                },
                vector_candidates=vector_candidates,
                keyword_candidates=keyword_candidates,
                union_vector_scores=vector_scores,
                trusted_record_hashes={
                    identifier: snapshot.record_hash
                    for identifier, snapshot in all_snapshots.items()
                },
                profile=self._profile,
                require_vector_scores=True,
            )
            if span:
                span.annotate(
                    metadata={
                        "result_count": len(results),
                        "provision_ids": [item.provision_id for item in results],
                        "scores": [item.final_score for item in results],
                    }
                )
        if stage_latencies_ms is not None:
            stage_latencies_ms["hybrid_ranking"] = (perf_counter() - started) * 1000
        return results


__all__ = ["RetrievalService"]
