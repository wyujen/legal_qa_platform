"""End-to-end deterministic RAG orchestration independent of FastAPI/UI."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from time import perf_counter
from typing import Any
from uuid import uuid4

from legal_qa_platform.domain.legal import sha256_text
from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.domain.qa import (
    LEGAL_NOTICE,
    ChatResponse,
    LegalQaResponse,
)
from legal_qa_platform.domain.retrieval import (
    ContextItem,
    RagContext,
    RetrievalResult,
)
from legal_qa_platform.ports.models import ChatMessage, ChatModel
from legal_qa_platform.ports.observability import Observability
from legal_qa_platform.ports.repositories import QaRunRepository
from legal_qa_platform.services.context import build_context
from legal_qa_platform.services.conversation import (
    ConversationService,
    ConversationTurn,
)
from legal_qa_platform.services.normalization import (
    NORMALIZATION_VERSION,
    normalize_text,
)
from legal_qa_platform.services.prompt import build_messages, response_schema
from legal_qa_platform.services.retrieval import RetrievalService
from legal_qa_platform.services.validation import (
    ResponseValidationError,
    parse_structured_response,
    validate_response,
)

logger = logging.getLogger(__name__)


def _duration_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


def _no_hit_response() -> LegalQaResponse:
    return LegalQaResponse(
        can_answer=False,
        summary="目前檢索到的現行條文不足以直接回答此問題。",
        conditions=[],
        exceptions=[],
        missing_information=["請補充更具體的法規名稱、條號或適用情境。"],
        citations=[],
        notice=LEGAL_NOTICE,
    )


def _model_messages(
    question: str,
    context: RagContext,
    history: Sequence[ConversationTurn],
) -> list[ChatMessage]:
    prompt_messages = build_messages(question, context)
    system = prompt_messages[0]
    user = prompt_messages[1]
    messages = [ChatMessage(role="system", content=system["content"])]
    history_block = ConversationService.render_untrusted_history(history)
    if history_block:
        messages.append(ChatMessage(role="user", content=history_block))
    messages.append(ChatMessage(role="user", content=user["content"]))
    return messages


def _retrieval_log_rows(
    results: Sequence[RetrievalResult],
    contexts: Sequence[ContextItem],
) -> list[dict[str, Any]]:
    excerpt_hashes = {item.provision_id: item.excerpt_hash for item in contexts}
    return [
        {
            "rank": item.rank,
            "provision_id": item.provision_id,
            "vector_score": item.vector_score,
            "keyword_score": item.keyword_score,
            "final_score": item.final_score,
            "official_content_hash": item.content_hash,
            "record_hash": item.record_hash,
            "embedding_input_hash": item.embedding_input_hash,
            "excerpt_hash": excerpt_hashes.get(item.provision_id),
        }
        for item in results
    ]


class QaService:
    """Compose normalization through validated answer and durable conversation."""

    def __init__(
        self,
        *,
        repository: QaRunRepository,
        retrieval: RetrievalService,
        chat_model: ChatModel,
        conversations: ConversationService,
        observability: Observability,
        profile: RagProfile,
    ) -> None:
        self._repository = repository
        self._retrieval = retrieval
        self._chat_model = chat_model
        self._conversations = conversations
        self._observability = observability
        self._profile = profile

    async def _best_effort(self, operation: Callable[[], Awaitable[Any]]) -> bool:
        try:
            await operation()
            return True
        except Exception:
            logger.warning("Non-critical PostgreSQL run logging failed", exc_info=False)
            return False

    async def answer(
        self,
        question: str,
        *,
        conversation_id: str | None = None,
    ) -> ChatResponse:
        overall_started = perf_counter()
        query_id = uuid4()
        stage_latencies: dict[str, float] = {}
        run_logged = False

        with self._observability.trace(
            "legal_qa_request",
            input={
                "question_hash": sha256_text(question),
                "question_length": len(question),
            },
            metadata={
                "profile": self._profile.name,
                "prompt": self._profile.prompt_name,
                "normalization": NORMALIZATION_VERSION,
                "embedding_model": self._profile.embedding_model,
                "chat_model": self._profile.chat_model,
            },
        ) as trace:
            try:
                started = perf_counter()
                with trace.span("normalize") as span:
                    normalized = normalize_text(question)
                    if not normalized:
                        raise ValueError("Question is empty after normalization.")
                    span.annotate(
                        output={
                            "normalized_question_hash": sha256_text(normalized),
                            "normalized_question_length": len(normalized),
                        }
                    )
                stage_latencies["normalize"] = _duration_ms(started)

                started = perf_counter()
                with trace.span(
                    "conversation_context",
                    metadata={"limit": self._profile.conversation_message_limit},
                ) as span:
                    conversation_uuid, history = await self._conversations.begin_turn(
                        conversation_id,
                        question,
                    )
                    span.annotate(metadata={"message_count": len(history)})
                stage_latencies["conversation_context"] = _duration_ms(started)

                run_logged = await self._best_effort(
                    lambda: self._repository.start_qa_run(
                        query_id=query_id,
                        conversation_id=conversation_uuid,
                        trace_id=trace.trace_id,
                        profile_name=self._profile.name,
                        prompt_name=self._profile.prompt_name,
                        normalization_version=NORMALIZATION_VERSION,
                        chat_model=self._profile.chat_model,
                        embedding_model=self._profile.embedding_model,
                        vector_collection=self._profile.vector_collection,
                        question=question,
                        normalized_question=normalized,
                    )
                )
                retrieval_results = await self._retrieval.retrieve(
                    normalized,
                    trace=trace,
                    stage_latencies_ms=stage_latencies,
                )

                contexts: list[ContextItem] = []
                if not retrieval_results:
                    response = _no_hit_response()
                else:
                    started = perf_counter()
                    with trace.span(
                        "context_build",
                        metadata={"top_k": self._profile.top_k},
                    ) as span:
                        context = build_context(
                            normalized,
                            retrieval_results,
                            self._profile,
                        )
                        contexts = list(context.items)
                        span.annotate(
                            metadata={
                                "provision_ids": [
                                    item.provision_id for item in context.items
                                ],
                                "excerpt_hashes": [
                                    item.excerpt_hash for item in context.items
                                ],
                            }
                        )
                    stage_latencies["context_build"] = _duration_ms(started)

                    messages = _model_messages(normalized, context, history)
                    started = perf_counter()
                    with trace.span(
                        "generation",
                        metadata={
                            "model": self._profile.chat_model,
                            "max_tokens": self._profile.chat_max_tokens,
                        },
                    ) as span:
                        completion = await self._chat_model.complete(
                            messages,
                            model=self._profile.chat_model,
                            max_tokens=self._profile.chat_max_tokens,
                            response_schema=response_schema(),
                        )
                        span.annotate(
                            metadata={
                                "model": completion.model,
                                "request_id": completion.request_id,
                                "usage": dict(completion.usage or {}),
                            }
                        )
                    stage_latencies["generation"] = _duration_ms(started)

                    started = perf_counter()
                    with trace.span("response_validation") as span:
                        try:
                            parsed = parse_structured_response(completion.content)
                            attempts = 1
                        except ResponseValidationError:
                            repair = ChatMessage(
                                role="user",
                                content=(
                                    "上一個輸出未通過 JSON Schema 驗證。"
                                    "請重新依原始問題、參考條文與同一 Schema輸出；"
                                    "只輸出單一 JSON 物件。"
                                ),
                            )
                            repaired = await self._chat_model.complete(
                                [*messages, repair],
                                model=self._profile.chat_model,
                                max_tokens=self._profile.chat_max_tokens,
                                response_schema=response_schema(),
                            )
                            parsed = parse_structured_response(repaired.content)
                            attempts = 2
                        span.annotate(metadata={"valid": True, "attempts": attempts})
                    stage_latencies["response_validation"] = _duration_ms(started)

                    started = perf_counter()
                    with trace.span("citation_validation") as span:
                        response = validate_response(
                            parsed,
                            retrieval_results,
                            max_list_items=self._profile.top_k,
                        )
                        span.annotate(
                            metadata={
                                "valid": True,
                                "citation_ids": [
                                    item.provision_id for item in response.citations
                                ],
                            }
                        )
                    stage_latencies["citation_validation"] = _duration_ms(started)

                await self._conversations.finish_turn(
                    conversation_uuid,
                    query_id=query_id,
                    response=response,
                )
                duration_ms = max(0, round(_duration_ms(overall_started)))
                stage_latencies["total"] = float(duration_ms)
                if run_logged:
                    await self._best_effort(
                        lambda: self._repository.record_qa_retrievals(
                            query_id,
                            _retrieval_log_rows(retrieval_results, contexts),
                        )
                    )
                    await self._best_effort(
                        lambda: self._repository.finish_qa_run(
                            query_id,
                            response=response.model_dump(mode="json"),
                            stage_latencies_ms=stage_latencies,
                        )
                    )
                trace.annotate(
                    output={
                        "can_answer": response.can_answer,
                        "citation_ids": [
                            item.provision_id for item in response.citations
                        ],
                    },
                    metadata={"duration_ms": duration_ms},
                )
                return ChatResponse(
                    query_id=str(query_id),
                    conversation_id=str(conversation_uuid),
                    question=question,
                    normalized_question=normalized,
                    profile=self._profile.name,
                    response=response,
                    retrieval_results=retrieval_results,
                    stage_latencies_ms=stage_latencies,
                    duration_ms=duration_ms,
                    error=None,
                )
            except Exception as exc:
                error_category = type(exc).__name__
                stage_latencies["total"] = _duration_ms(overall_started)
                if run_logged:
                    await self._best_effort(
                        lambda: self._repository.finish_qa_run(
                            query_id,
                            response=None,
                            stage_latencies_ms=stage_latencies,
                            error_category=error_category,
                        )
                    )
                trace.annotate(error=error_category)
                raise


__all__ = ["QaService"]
