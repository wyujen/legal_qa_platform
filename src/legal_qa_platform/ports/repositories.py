"""Application-owned repository contracts and persistence transfer objects.

The application core depends on these protocols.  PostgreSQL is one adapter;
tests and future persistence implementations can satisfy the same contracts
without importing infrastructure types into domain services.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from legal_qa_platform.domain.legal import LegalProvision


@dataclass(frozen=True, slots=True)
class SyncRun:
    run_id: UUID
    generation: int


@dataclass(frozen=True, slots=True)
class ProvisionSyncState:
    provision_id: int
    canonical_stable_key: str | None
    document_name: str | None
    article_no: str | None
    paragraph_no: int | None
    subparagraph_no: int | None
    identity_status: str
    record_hash: str | None
    embedding_input_hash: str | None
    embedding_model: str | None
    vector_collection: str | None
    vector_generation: int | None
    is_current: bool


@dataclass(frozen=True, slots=True)
class ProvisionWrite:
    provision: LegalProvision
    canonical_stable_key: str
    official_content_hash: str
    record_hash: str
    embedding_input_hash: str
    search_compact: str
    vector_generation: int
    vector_action: Literal["upserted", "reused"]


@dataclass(frozen=True, slots=True)
class PublishSummary:
    provision_count: int
    deactivated_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ProvisionSnapshot:
    provision: LegalProvision
    official_content_hash: str
    record_hash: str
    embedding_input_hash: str
    embedding_model: str
    vector_collection: str
    vector_generation: int


class RepositoryLifecycle(Protocol):
    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def is_ready(self) -> bool: ...

    async def has_published_snapshot(
        self,
        *,
        embedding_model: str,
        embedding_dimension: int,
        vector_collection: str,
    ) -> bool: ...


class MigrationRepository(Protocol):
    async def apply_migrations(self, directory: Path) -> tuple[str, ...]: ...


class LegalRepository(Protocol):
    async def get_provisions_by_ids(
        self, provision_ids: Sequence[int]
    ) -> dict[int, ProvisionSnapshot]: ...

    async def keyword_candidates(
        self,
        *,
        compact_query: str,
        terms: Sequence[str],
        limit: int,
    ) -> list[ProvisionSnapshot]: ...


class IngestionRepository(Protocol):
    async def start_collection_run(
        self,
        *,
        mode: Literal["full_snapshot", "partial"],
        source_label: str,
        source_fingerprint: str,
        embedding_model: str,
        embedding_dimension: int,
        vector_collection: str,
        document_count: int,
        provision_count: int,
    ) -> SyncRun: ...

    async def mark_vectors_staged(
        self,
        run_id: UUID,
        *,
        embedded_count: int,
        reused_vector_count: int,
    ) -> None: ...

    async def mark_run_failed(self, run_id: UUID, category: str) -> None: ...

    async def get_sync_states(
        self, provision_ids: Sequence[int]
    ) -> dict[int, ProvisionSyncState]: ...

    async def get_max_provision_id(self) -> int: ...

    async def publish_snapshot(
        self,
        run: SyncRun,
        writes: Sequence[ProvisionWrite],
        *,
        full_snapshot: bool,
    ) -> PublishSummary: ...


class ConversationRepository(Protocol):
    async def create_conversation(
        self,
        *,
        user_id: str | None = None,
        conversation_id: UUID | None = None,
    ) -> UUID: ...

    async def conversation_status(self, conversation_id: UUID) -> str | None: ...

    async def append_message(
        self,
        conversation_id: UUID,
        *,
        role: Literal["user", "assistant", "system"],
        content: str,
        query_id: UUID | None = None,
    ) -> UUID: ...

    async def recent_messages(
        self,
        conversation_id: UUID,
        *,
        limit: int,
    ) -> list[dict[str, str]]: ...


class QaRunRepository(Protocol):
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
    ) -> None: ...

    async def finish_qa_run(
        self,
        query_id: UUID,
        *,
        response: Mapping[str, Any] | None,
        stage_latencies_ms: Mapping[str, int | float],
        error_category: str | None = None,
    ) -> None: ...

    async def record_qa_retrievals(
        self,
        query_id: UUID,
        rows: Sequence[Mapping[str, Any]],
    ) -> None: ...

    async def save_feedback(
        self,
        *,
        query_id: UUID,
        conversation_id: UUID | None,
        rating: int | None,
        category: str | None,
        comment: str | None,
    ) -> UUID: ...


class ApplicationRepository(
    RepositoryLifecycle,
    MigrationRepository,
    LegalRepository,
    IngestionRepository,
    ConversationRepository,
    QaRunRepository,
    Protocol,
):
    """Complete persistence boundary used by the composition root."""


__all__ = [
    "ApplicationRepository",
    "ConversationRepository",
    "IngestionRepository",
    "LegalRepository",
    "MigrationRepository",
    "ProvisionSnapshot",
    "ProvisionSyncState",
    "ProvisionWrite",
    "PublishSummary",
    "QaRunRepository",
    "RepositoryLifecycle",
    "SyncRun",
]
