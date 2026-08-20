"""One composition root for API, scripts, and tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from legal_qa_platform.adapters.litellm import LiteLLMGateway
from legal_qa_platform.adapters.observability import NoopObservability
from legal_qa_platform.adapters.postgres import (
    PostgresRepository,
    create_postgres_pool,
)
from legal_qa_platform.adapters.qdrant import QdrantVectorStore
from legal_qa_platform.config import RuntimeSettings
from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.ports.observability import Observability
from legal_qa_platform.ports.repositories import ApplicationRepository
from legal_qa_platform.services.conversation import ConversationService
from legal_qa_platform.services.profile_loader import load_profile
from legal_qa_platform.services.qa import QaService
from legal_qa_platform.services.retrieval import RetrievalService


@dataclass(slots=True)
class ApplicationContainer:
    settings: RuntimeSettings
    profile: RagProfile
    repository: ApplicationRepository
    qdrant: QdrantVectorStore
    litellm: LiteLLMGateway
    retrieval: RetrievalService
    conversations: ConversationService
    qa: QaService

    @classmethod
    def build(
        cls,
        *,
        settings: RuntimeSettings | None = None,
        profile_path: Path | None = None,
        observability: Observability | None = None,
    ) -> ApplicationContainer:
        runtime = settings or RuntimeSettings()
        endpoints = runtime.require_runtime()
        profile = load_profile(profile_path) if profile_path else load_profile()
        assert runtime.litellm_api_key is not None
        assert runtime.qdrant_api_key is not None

        litellm = LiteLLMGateway(
            endpoints.litellm_url,
            runtime.litellm_api_key,
        )
        qdrant = QdrantVectorStore(
            endpoints.qdrant_http_url,
            runtime.qdrant_api_key,
        )
        repository = PostgresRepository(create_postgres_pool(runtime))
        tracing = observability or NoopObservability()
        retrieval = RetrievalService(
            repository=repository,
            vector_store=qdrant,
            embeddings=litellm,
            profile=profile,
        )
        conversations = ConversationService(
            repository,
            message_limit=profile.conversation_message_limit,
        )
        qa = QaService(
            repository=repository,
            retrieval=retrieval,
            chat_model=litellm,
            conversations=conversations,
            observability=tracing,
            profile=profile,
        )
        return cls(
            settings=runtime,
            profile=profile,
            repository=repository,
            qdrant=qdrant,
            litellm=litellm,
            retrieval=retrieval,
            conversations=conversations,
            qa=qa,
        )

    async def open(self) -> None:
        await self.repository.open()

    async def close(self) -> None:
        await asyncio.gather(
            self.repository.close(),
            self.qdrant.aclose(),
            self.litellm.aclose(),
            return_exceptions=True,
        )

    async def readiness(self) -> dict[str, bool]:
        (
            postgres,
            published_snapshot,
            qdrant,
            qdrant_collection,
            litellm,
        ) = await asyncio.gather(
            self.repository.is_ready(),
            self.repository.has_published_snapshot(
                embedding_model=self.profile.embedding_model,
                embedding_dimension=self.profile.embedding_dimension,
                vector_collection=self.profile.vector_collection,
            ),
            self.qdrant.is_ready(),
            self.qdrant.collection_is_ready(
                self.profile.vector_collection,
                dimension=self.profile.embedding_dimension,
            ),
            self.litellm.is_ready(),
        )
        return {
            "postgresql": postgres,
            "published_snapshot": published_snapshot,
            "qdrant": qdrant,
            "qdrant_collection": qdrant_collection,
            "litellm": litellm,
        }


__all__ = ["ApplicationContainer"]
