"""Evaluate the checked-in 100-question bank through production services.

Expected answers, keywords, and provision IDs are used only after a production
retrieval or QA call returns. Reports contain metrics and stable identifiers,
not question text, generated answer text, credentials, endpoints, or headers.
"""

from __future__ import annotations

import argparse
import hashlib
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Literal, cast

from pydantic import ValidationError

from legal_qa_platform import __version__
from legal_qa_platform.async_runtime import run_async
from legal_qa_platform.config import RuntimeSettings
from legal_qa_platform.container import ApplicationContainer
from legal_qa_platform.domain.qa import LegalQaResponse, QuestionBankItem
from legal_qa_platform.services.data_loader import load_data_bundle
from legal_qa_platform.services.normalization import normalize_text

try:
    from scripts._cli import (
        PROJECT_ROOT,
        latency_summary,
        print_missing_variables,
        repository_output_path,
        repository_path,
        safe_exception_category,
        utc_run_stamp,
        write_json,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from _cli import (  # type: ignore[import-not-found, no-redef]
        PROJECT_ROOT,
        latency_summary,
        print_missing_variables,
        repository_output_path,
        repository_path,
        safe_exception_category,
        utc_run_stamp,
        write_json,
    )

DEFAULT_PROVISIONS_PATH = PROJECT_ROOT / "data" / "legal_provisions.json"
DEFAULT_QUESTIONS_PATH = PROJECT_ROOT / "data" / "qa_test_questions.json"
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "profiles" / "platform-baseline-v1.json"


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    """Historical hit and mathematically distinct retrieval measurements."""

    historical_hit_at_k: bool
    true_recall_at_k: float
    reciprocal_rank: float


@dataclass(frozen=True, slots=True)
class AnswerMetrics:
    """Automatic answer diagnostics; these are not legal correctness judgments."""

    structured_answer_valid: bool
    answer_nonempty: bool
    can_answer: bool
    citation_allowlist_valid: bool
    citation_expected_hit: bool
    citation_expected_precision: float
    citation_expected_recall: float
    expected_keyword_recall: float
    reference_bigram_f1: float


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    question_id: str
    expected_provision_count: int
    retrieved_provision_ids: tuple[int, ...]
    citation_provision_ids: tuple[int, ...]
    retrieval: RetrievalMetrics
    answer: AnswerMetrics | None
    stage_latencies_ms: dict[str, float]
    duration_ms: float
    error_category: str | None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def retrieval_metrics(
    expected_provision_ids: Sequence[int],
    retrieved_provision_ids: Sequence[int],
) -> RetrievalMetrics:
    """Keep legacy any-hit separate from true Recall@K and MRR."""

    expected = set(expected_provision_ids)
    if not expected:
        raise ValueError("Expected provision IDs cannot be empty.")
    retrieved = list(retrieved_provision_ids)
    intersection = expected.intersection(retrieved)
    first_rank = next(
        (index for index, value in enumerate(retrieved, start=1) if value in expected),
        None,
    )
    return RetrievalMetrics(
        historical_hit_at_k=bool(intersection),
        true_recall_at_k=len(intersection) / len(expected),
        reciprocal_rank=0.0 if first_rank is None else 1.0 / first_rank,
    )


def _compact_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(normalized.split())


def _bigrams(value: str) -> set[str]:
    compact = _compact_text(value)
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[index : index + 2] for index in range(len(compact) - 1)}


def _set_f1(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left.intersection(right))
    if overlap == 0:
        return 0.0
    precision = overlap / len(left)
    recall = overlap / len(right)
    return 2 * precision * recall / (precision + recall)


def answer_metrics(
    item: QuestionBankItem,
    response: LegalQaResponse,
    retrieved_provision_ids: Sequence[int],
) -> AnswerMetrics:
    """Compare a validated response with evaluation-only labels after inference."""

    answer_text = " ".join(
        [
            response.summary,
            *response.conditions,
            *response.exceptions,
            *response.missing_information,
        ]
    )
    compact_answer = _compact_text(answer_text)
    citations = [citation.provision_id for citation in response.citations]
    expected = set(item.expected_provision_ids)
    cited_expected = expected.intersection(citations)
    keyword_hits = sum(
        _compact_text(keyword) in compact_answer for keyword in item.expected_keywords
    )
    return AnswerMetrics(
        structured_answer_valid=True,
        answer_nonempty=bool(compact_answer),
        can_answer=response.can_answer,
        citation_allowlist_valid=set(citations).issubset(retrieved_provision_ids),
        citation_expected_hit=bool(cited_expected),
        citation_expected_precision=(
            len(cited_expected) / len(set(citations)) if citations else 0.0
        ),
        citation_expected_recall=len(cited_expected) / len(expected),
        expected_keyword_recall=keyword_hits / len(item.expected_keywords),
        reference_bigram_f1=_set_f1(
            _bigrams(answer_text),
            _bigrams(item.expected_answer),
        ),
    )


def _failed_case(
    item: QuestionBankItem, started: float, exc: Exception
) -> EvaluationCase:
    return EvaluationCase(
        question_id=item.question_id,
        expected_provision_count=len(item.expected_provision_ids),
        retrieved_provision_ids=(),
        citation_provision_ids=(),
        retrieval=retrieval_metrics(item.expected_provision_ids, ()),
        answer=None,
        stage_latencies_ms={},
        duration_ms=(perf_counter() - started) * 1_000,
        error_category=safe_exception_category(exc),
    )


async def evaluate_case(
    container: ApplicationContainer,
    item: QuestionBankItem,
    *,
    mode: Literal["retrieval", "full"],
) -> EvaluationCase:
    """Run one production call before consulting any expected value."""

    started = perf_counter()
    try:
        response: LegalQaResponse | None = None
        if mode == "full":
            qa_result = await container.qa.answer(item.question)
            results = qa_result.retrieval_results
            response = qa_result.response
            stage_latencies = dict(qa_result.stage_latencies_ms)
            duration_ms = float(qa_result.duration_ms)
        else:
            normalized = normalize_text(item.question)
            stage_latencies = {}
            results = await container.retrieval.retrieve(
                normalized,
                stage_latencies_ms=stage_latencies,
            )
            duration_ms = (perf_counter() - started) * 1_000
            stage_latencies["total"] = duration_ms
    except Exception as exc:
        return _failed_case(item, started, exc)

    retrieved_ids = tuple(result.provision_id for result in results)
    citations = (
        tuple(citation.provision_id for citation in response.citations)
        if response is not None
        else ()
    )
    return EvaluationCase(
        question_id=item.question_id,
        expected_provision_count=len(item.expected_provision_ids),
        retrieved_provision_ids=retrieved_ids,
        citation_provision_ids=citations,
        retrieval=retrieval_metrics(item.expected_provision_ids, retrieved_ids),
        answer=(
            answer_metrics(item, response, retrieved_ids)
            if response is not None
            else None
        ),
        stage_latencies_ms=stage_latencies,
        duration_ms=duration_ms,
        error_category=None,
    )


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def aggregate_results(cases: Sequence[EvaluationCase]) -> dict[str, object]:
    if not cases:
        raise ValueError("At least one evaluation case is required.")
    answer_cases = [item.answer for item in cases if item.answer is not None]
    errors = Counter(
        item.error_category for item in cases if item.error_category is not None
    )
    stages = sorted({name for item in cases for name in item.stage_latencies_ms})
    return {
        "case_count": len(cases),
        "success_count": sum(item.error_category is None for item in cases),
        "error_count": sum(item.error_category is not None for item in cases),
        "error_categories": dict(sorted(errors.items())),
        "retrieval": {
            "historical_hit_at_k_rate": _mean(
                [float(item.retrieval.historical_hit_at_k) for item in cases]
            ),
            "true_recall_at_k_mean": _mean(
                [item.retrieval.true_recall_at_k for item in cases]
            ),
            "mean_reciprocal_rank": _mean(
                [item.retrieval.reciprocal_rank for item in cases]
            ),
        },
        "answer": {
            "evaluated_count": len(answer_cases),
            "structured_answer_pass_rate_all_cases": _mean(
                [float(item.answer is not None) for item in cases]
            ),
            "answer_nonempty_rate": _mean(
                [float(item.answer_nonempty) for item in answer_cases]
            ),
            "can_answer_rate": _mean([float(item.can_answer) for item in answer_cases]),
            "citation_allowlist_pass_rate": _mean(
                [float(item.citation_allowlist_valid) for item in answer_cases]
            ),
            "citation_expected_hit_rate": _mean(
                [float(item.citation_expected_hit) for item in answer_cases]
            ),
            "citation_expected_precision_mean": _mean(
                [item.citation_expected_precision for item in answer_cases]
            ),
            "citation_expected_recall_mean": _mean(
                [item.citation_expected_recall for item in answer_cases]
            ),
            "expected_keyword_recall_mean": _mean(
                [item.expected_keyword_recall for item in answer_cases]
            ),
            "reference_bigram_f1_mean": _mean(
                [item.reference_bigram_f1 for item in answer_cases]
            ),
            "automatic_metrics_are_not_legal_correctness": True,
        },
        "latency_ms": {
            "end_to_end": latency_summary([item.duration_ms for item in cases]),
            "stages": {
                stage: latency_summary(
                    [
                        item.stage_latencies_ms[stage]
                        for item in cases
                        if stage in item.stage_latencies_ms
                    ]
                )
                for stage in stages
            },
        },
    }


def _case_payload(item: EvaluationCase) -> dict[str, object]:
    payload = asdict(item)
    return cast(dict[str, object], payload)


async def run_evaluation(
    *,
    settings: RuntimeSettings,
    provisions_path: Path,
    questions_path: Path,
    profile_path: Path,
    output_path: Path,
    mode: Literal["retrieval", "full"],
    limit: int | None,
) -> int:
    try:
        bundle = load_data_bundle(provisions_path, questions_path)
        selected = bundle.questions[:limit] if limit is not None else bundle.questions
        container = ApplicationContainer.build(
            settings=settings,
            profile_path=profile_path,
        )
    except Exception as exc:
        print(f"[FAIL] evaluation setup category={safe_exception_category(exc)}")
        return 1

    cases: list[EvaluationCase] = []
    try:
        await container.open()
        for index, item in enumerate(selected, start=1):
            cases.append(await evaluate_case(container, item, mode=mode))
            print(
                f"[RUN] evaluation progress={index}/{len(selected)} "
                f"id={item.question_id}"
            )
    except Exception as exc:
        print(f"[FAIL] evaluation runtime category={safe_exception_category(exc)}")
        return 1
    finally:
        await container.close()

    report = {
        "schema_version": 1,
        "created_at_utc": utc_run_stamp(),
        "application_version": __version__,
        "mode": mode,
        "dataset": {
            "question_count": len(bundle.questions),
            "evaluated_count": len(cases),
            "questions_sha256": _sha256_file(questions_path),
            "provisions_sha256": _sha256_file(provisions_path),
        },
        "profile_sha256": _sha256_file(profile_path),
        "profile": container.profile.model_dump(mode="json"),
        "metric_definitions": {
            "historical_hit_at_k": "1 when any expected provision appears in Top K",
            "true_recall_at_k": (
                "retrieved expected provisions / all expected provisions"
            ),
            "reciprocal_rank": "1 / rank of the first expected provision, else 0",
            "expected_keyword_recall": (
                "expected keyword labels present in validated answer"
            ),
            "reference_bigram_f1": (
                "diagnostic character-bigram overlap; not legal correctness"
            ),
        },
        "aggregate": aggregate_results(cases),
        "cases": [_case_payload(item) for item in cases],
    }
    try:
        write_json(output_path, report)
    except Exception as exc:
        print(f"[FAIL] evaluation report category={safe_exception_category(exc)}")
        return 1

    error_count = sum(item.error_category is not None for item in cases)
    relative_output = output_path.relative_to(PROJECT_ROOT).as_posix()
    if error_count:
        print(
            f"[FAIL] evaluation completed cases={len(cases)} errors={error_count} "
            f"report={relative_output}"
        )
        return 1
    print(f"[PASS] evaluation completed cases={len(cases)} report={relative_output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the checked-in legal QA evaluation through production services."
        )
    )
    parser.add_argument("--mode", choices=("retrieval", "full"), default="full")
    parser.add_argument("--provisions", default="data/legal_provisions.json")
    parser.add_argument("--questions", default="data/qa_test_questions.json")
    parser.add_argument("--profile", default="profiles/platform-baseline-v1.json")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional 1..100 diagnostic subset; omit for the official 100 cases.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Repository-relative report path under evaluation-results by default.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit is not None and not 1 <= args.limit <= 100:
        print("[FAIL] --limit must be between 1 and 100.")
        return 2
    default_output = (
        PROJECT_ROOT / "evaluation-results" / f"evaluation-{utc_run_stamp()}.json"
    )
    try:
        provisions_path = repository_path(
            args.provisions, default=DEFAULT_PROVISIONS_PATH
        )
        questions_path = repository_path(args.questions, default=DEFAULT_QUESTIONS_PATH)
        profile_path = repository_path(args.profile, default=DEFAULT_PROFILE_PATH)
        output_path = repository_output_path(args.output, default=default_output)
        settings = RuntimeSettings()
    except (ValueError, ValidationError):
        print("[FAIL] evaluation configuration is invalid; check documented types.")
        return 2
    missing = settings.missing_for_runtime()
    if missing:
        print_missing_variables(missing, command="python scripts/evaluate.py")
        return 2
    return run_async(
        run_evaluation(
            settings=settings,
            provisions_path=provisions_path,
            questions_path=questions_path,
            profile_path=profile_path,
            output_path=output_path,
            mode=cast(Literal["retrieval", "full"], args.mode),
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
