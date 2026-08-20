"""Idempotent legal snapshot synchronization across PostgreSQL and Qdrant."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from legal_qa_platform.domain.legal import (
    LegalProvision,
    build_embedding_text,
    canonical_json_hash,
    canonicalize_identity_text,
    provision_embedding_input_hash,
    provision_official_content_hash,
    provision_record_hash,
    provisions_fingerprint,
)
from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.errors import IdentityConflictError
from legal_qa_platform.ports.models import EmbeddingProvider
from legal_qa_platform.ports.repositories import (
    IngestionRepository,
    ProvisionSyncState,
    ProvisionWrite,
)
from legal_qa_platform.ports.vector_store import VectorPoint, VectorStore
from legal_qa_platform.services.normalization import compact_keyword_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PreparedProvision:
    provision: LegalProvision
    canonical_stable_key: str
    official_content_hash: str
    record_hash: str
    embedding_input_hash: str
    embedding_text: str
    search_compact: str


@dataclass(frozen=True, slots=True)
class IngestionSummary:
    run_id: str
    generation: int
    provision_count: int
    embedded_count: int
    reused_vector_count: int
    deactivated_count: int
    qdrant_cleanup_pending: bool


def prepare_provision(provision: LegalProvision) -> PreparedProvision:
    embedding_text = build_embedding_text(provision)
    return PreparedProvision(
        provision=provision,
        canonical_stable_key=canonical_json_hash(provision.stable_key),
        official_content_hash=provision_official_content_hash(provision),
        record_hash=provision_record_hash(provision),
        embedding_input_hash=provision_embedding_input_hash(provision),
        embedding_text=embedding_text,
        search_compact=compact_keyword_text(provision.search_text),
    )


def _identity_is_compatible(
    state: ProvisionSyncState,
    prepared: PreparedProvision,
) -> bool:
    if state.identity_status == "reserved_legacy":
        return False
    if state.canonical_stable_key == prepared.canonical_stable_key:
        return True
    provision = prepared.provision
    return (
        state.document_name == provision.document_name
        and state.article_no == provision.article_no
        and state.paragraph_no is None
        and provision.paragraph_no == 1
        and state.subparagraph_no == provision.subparagraph_no
    )


def _point_payload(
    item: PreparedProvision,
    *,
    profile: RagProfile,
    vector_generation: int,
) -> dict[str, object]:
    provision = item.provision
    return {
        "provision_id": provision.provision_id,
        "document_name": provision.document_name,
        "article_no": provision.article_no,
        "official_content_hash": item.official_content_hash,
        "record_hash": item.record_hash,
        "embedding_input_hash": item.embedding_input_hash,
        "embedding_model": profile.embedding_model,
        "vector_generation": vector_generation,
        "is_current": True,
    }


def _can_reuse_vector(
    item: PreparedProvision,
    state: ProvisionSyncState | None,
    payload: object,
    profile: RagProfile,
) -> bool:
    if state is None or not isinstance(payload, dict):
        return False
    return bool(
        state.embedding_input_hash == item.embedding_input_hash
        and state.embedding_model == profile.embedding_model
        and state.vector_collection == profile.vector_collection
        and state.vector_generation is not None
        and payload.get("provision_id") == item.provision.provision_id
        and payload.get("embedding_input_hash") == item.embedding_input_hash
        and payload.get("embedding_model") == profile.embedding_model
    )


class IngestionService:
    """Coordinate a recoverable Qdrant-stage then PostgreSQL-publish workflow."""

    def __init__(
        self,
        *,
        repository: IngestionRepository,
        vector_store: VectorStore,
        embeddings: EmbeddingProvider,
        profile: RagProfile,
        embedding_batch_size: int = 32,
        vector_batch_size: int = 64,
    ) -> None:
        if embedding_batch_size <= 0 or vector_batch_size <= 0:
            raise ValueError("Ingestion batch sizes must be positive.")
        self._repository = repository
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._profile = profile
        self._embedding_batch_size = embedding_batch_size
        self._vector_batch_size = vector_batch_size

    async def sync(
        self,
        provisions: Sequence[LegalProvision],
        *,
        mode: Literal["full_snapshot", "partial"],
        source_label: str = "legal_provisions.json",
    ) -> IngestionSummary:
        if mode not in {"full_snapshot", "partial"}:
            raise ValueError("mode must be full_snapshot or partial")
        if not provisions:
            raise ValueError("Refusing to synchronize an empty legal snapshot.")
        if any(not item.is_active for item in provisions):
            raise ValueError("Incoming synchronization data must be current-only.")
        prepared = [prepare_provision(item) for item in provisions]
        ids = [item.provision.provision_id for item in prepared]
        if len(ids) != len(set(ids)):
            raise IdentityConflictError("Incoming provision IDs must be unique.")
        keys = [item.canonical_stable_key for item in prepared]
        if len(keys) != len(set(keys)):
            raise IdentityConflictError("Incoming stable keys must be unique.")
        document_names: dict[str, str] = {}
        for item in prepared:
            raw_name = item.provision.document_name
            canonical_name = canonicalize_identity_text(raw_name)
            existing_name = document_names.setdefault(canonical_name, raw_name)
            if existing_name != raw_name:
                raise IdentityConflictError(
                    "Canonical document names must not have multiple raw spellings."
                )
        sort_orders = [item.provision.sort_order for item in prepared]
        if len(sort_orders) != len(set(sort_orders)) or sort_orders != sorted(
            sort_orders
        ):
            raise IdentityConflictError(
                "Incoming global sort_order values must be unique and ascending."
            )
        if mode == "full_snapshot" and sort_orders != list(
            range(1, len(sort_orders) + 1)
        ):
            raise IdentityConflictError(
                "A full snapshot must have contiguous global sort_order values."
            )

        run = await self._repository.start_collection_run(
            mode=mode,
            source_label=source_label,
            source_fingerprint=provisions_fingerprint(list(provisions)),
            embedding_model=self._profile.embedding_model,
            embedding_dimension=self._profile.embedding_dimension,
            vector_collection=self._profile.vector_collection,
            document_count=len({item.provision.document_name for item in prepared}),
            provision_count=len(prepared),
        )
        published = False
        try:
            await self._vector_store.ensure_collection(
                self._profile.vector_collection,
                dimension=self._profile.embedding_dimension,
            )
            states = await self._repository.get_sync_states(ids)
            for item in prepared:
                state = states.get(item.provision.provision_id)
                if state is not None and not _identity_is_compatible(state, item):
                    raise IdentityConflictError(
                        "A provision ID would be reassigned to another stable key."
                    )

            payloads = await self._vector_store.get_payloads(
                self._profile.vector_collection,
                ids,
            )
            to_embed: list[PreparedProvision] = []
            reused: list[PreparedProvision] = []
            for item in prepared:
                if _can_reuse_vector(
                    item,
                    states.get(item.provision.provision_id),
                    payloads.get(item.provision.provision_id),
                    self._profile,
                ):
                    reused.append(item)
                else:
                    to_embed.append(item)

            points: list[VectorPoint] = []
            for start in range(0, len(to_embed), self._embedding_batch_size):
                batch = to_embed[start : start + self._embedding_batch_size]
                vectors = await self._embeddings.embed(
                    [item.embedding_text for item in batch],
                    model=self._profile.embedding_model,
                    expected_dimension=self._profile.embedding_dimension,
                )
                if len(vectors) != len(batch):
                    raise RuntimeError(
                        "Embedding provider returned a wrong batch size."
                    )
                points.extend(
                    VectorPoint(
                        point_id=item.provision.provision_id,
                        vector=vector,
                        payload=_point_payload(
                            item,
                            profile=self._profile,
                            vector_generation=run.generation,
                        ),
                    )
                    for item, vector in zip(batch, vectors, strict=True)
                )

            for start in range(0, len(points), self._vector_batch_size):
                await self._vector_store.upsert(
                    self._profile.vector_collection,
                    points[start : start + self._vector_batch_size],
                )

            # Reused vectors retain their original vector generation, but their
            # non-vector payload is refreshed when record metadata changed or a
            # previously retired provision becomes current again.
            for item in reused:
                state = states[item.provision.provision_id]
                assert state.vector_generation is not None
                desired = _point_payload(
                    item,
                    profile=self._profile,
                    vector_generation=state.vector_generation,
                )
                if payloads.get(item.provision.provision_id) != desired:
                    await self._vector_store.set_payload(
                        self._profile.vector_collection,
                        [item.provision.provision_id],
                        desired,
                    )

            await self._repository.mark_vectors_staged(
                run.run_id,
                embedded_count=len(to_embed),
                reused_vector_count=len(reused),
            )
            writes: list[ProvisionWrite] = []
            embedded_ids = {item.provision.provision_id for item in to_embed}
            for item in prepared:
                state = states.get(item.provision.provision_id)
                vector_generation = (
                    run.generation
                    if item.provision.provision_id in embedded_ids
                    else state.vector_generation
                    if state is not None and state.vector_generation is not None
                    else run.generation
                )
                writes.append(
                    ProvisionWrite(
                        provision=item.provision,
                        canonical_stable_key=item.canonical_stable_key,
                        official_content_hash=item.official_content_hash,
                        record_hash=item.record_hash,
                        embedding_input_hash=item.embedding_input_hash,
                        search_compact=item.search_compact,
                        vector_generation=vector_generation,
                        vector_action="upserted"
                        if item.provision.provision_id in embedded_ids
                        else "reused",
                    )
                )
            publish = await self._repository.publish_snapshot(
                run,
                writes,
                full_snapshot=mode == "full_snapshot",
            )
            published = True
        except Exception as exc:
            if not published:
                try:
                    await self._repository.mark_run_failed(
                        run.run_id, type(exc).__name__
                    )
                except Exception:
                    logger.warning(
                        "Could not persist collection-run failure state",
                        exc_info=False,
                    )
            raise

        cleanup_pending = False
        if publish.deactivated_ids:
            try:
                await self._vector_store.set_payload(
                    self._profile.vector_collection,
                    list(publish.deactivated_ids),
                    {"is_current": False},
                )
            except Exception:
                # PostgreSQL remains authoritative and retrieval revalidates all
                # candidates. This affects Qdrant efficiency, not answer trust.
                cleanup_pending = True
                logger.warning(
                    "Qdrant deactivation cleanup is pending",
                    exc_info=False,
                )

        return IngestionSummary(
            run_id=str(run.run_id),
            generation=run.generation,
            provision_count=len(prepared),
            embedded_count=len(to_embed),
            reused_vector_count=len(reused),
            deactivated_count=len(publish.deactivated_ids),
            qdrant_cleanup_pending=cleanup_pending,
        )


__all__ = [
    "IngestionService",
    "IngestionSummary",
    "PreparedProvision",
    "prepare_provision",
]
