from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from legal_qa_platform.domain.qa import (
    Citation,
    LegalQaResponse,
    QuestionBankItem,
)
from legal_qa_platform.domain.retrieval import RetrievalResult

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.evaluate import (  # noqa: E402
    EvaluationCase,
    aggregate_results,
    answer_metrics,
    evaluate_case,
    retrieval_metrics,
)

HASH = "a" * 64


def _question() -> QuestionBankItem:
    return QuestionBankItem(
        question_id="Q001",
        question="學生申請期限為何？",
        expected_answer="應在十日內提出申請。",
        expected_keywords=["十日", "申請"],
        expected_provision_ids=[10, 20],
        document_name="測試規定",
        article_no="第1條",
    )


def _retrieval(provision_id: int, rank: int) -> RetrievalResult:
    return RetrievalResult(
        provision_id=provision_id,
        document_name="測試規定",
        article_no=f"第{rank}條",
        content="應在十日內提出申請。",
        content_hash=HASH,
        record_hash=HASH,
        embedding_input_hash=HASH,
        vector_score=0.8,
        keyword_score=0.6,
        final_score=0.73,
        rank=rank,
    )


def _answer() -> LegalQaResponse:
    return LegalQaResponse(
        can_answer=True,
        summary="學生應在十日內提出申請。",
        citations=[
            Citation(
                provision_id=20,
                document_name="測試規定",
                article_no="第2條",
            )
        ],
    )


def test_retrieval_metrics_separate_historical_hit_recall_and_mrr() -> None:
    metrics = retrieval_metrics([10, 20], [30, 20])

    assert metrics.historical_hit_at_k is True
    assert metrics.true_recall_at_k == 0.5
    assert metrics.reciprocal_rank == 0.5


def test_answer_metrics_cover_keywords_citations_and_reference_overlap() -> None:
    metrics = answer_metrics(_question(), _answer(), [20, 30])

    assert metrics.structured_answer_valid is True
    assert metrics.answer_nonempty is True
    assert metrics.citation_allowlist_valid is True
    assert metrics.citation_expected_hit is True
    assert metrics.citation_expected_precision == 1.0
    assert metrics.citation_expected_recall == 0.5
    assert metrics.expected_keyword_recall == 1.0
    assert metrics.reference_bigram_f1 > 0.5


@pytest.mark.asyncio
async def test_expected_labels_are_not_sent_to_the_production_qa_call() -> None:
    item = _question().model_copy(
        update={
            "expected_answer": "DO_NOT_SEND_EXPECTED_ANSWER",
            "expected_keywords": ["DO_NOT_SEND_EXPECTED_KEYWORD"],
        }
    )

    class FakeQa:
        def __init__(self) -> None:
            self.received: list[str] = []

        async def answer(self, question: str) -> Any:
            self.received.append(question)
            return SimpleNamespace(
                retrieval_results=[_retrieval(20, 1)],
                response=_answer(),
                stage_latencies_ms={"total": 12.0},
                duration_ms=12,
            )

    qa = FakeQa()
    container = SimpleNamespace(qa=qa)

    result = await evaluate_case(container, item, mode="full")  # type: ignore[arg-type]

    assert qa.received == [item.question]
    assert item.expected_answer not in qa.received
    assert item.expected_keywords[0] not in qa.received
    assert result.error_category is None


def test_aggregate_reports_distinct_retrieval_and_answer_metrics() -> None:
    item = _question()
    first = EvaluationCase(
        question_id=item.question_id,
        expected_provision_count=2,
        retrieved_provision_ids=(20,),
        citation_provision_ids=(20,),
        retrieval=retrieval_metrics([10, 20], [20]),
        answer=answer_metrics(item, _answer(), [20]),
        stage_latencies_ms={"generation": 8.0, "total": 10.0},
        duration_ms=10.0,
        error_category=None,
    )
    second = EvaluationCase(
        question_id="Q002",
        expected_provision_count=1,
        retrieved_provision_ids=(),
        citation_provision_ids=(),
        retrieval=retrieval_metrics([30], []),
        answer=None,
        stage_latencies_ms={},
        duration_ms=20.0,
        error_category="timeout",
    )

    aggregate = aggregate_results([first, second])
    retrieval = aggregate["retrieval"]
    answer = aggregate["answer"]

    assert isinstance(retrieval, dict)
    assert retrieval["historical_hit_at_k_rate"] == 0.5
    assert retrieval["true_recall_at_k_mean"] == 0.25
    assert isinstance(answer, dict)
    assert answer["structured_answer_pass_rate_all_cases"] == 0.5
