"""Strict loaders for checked-in legal data and the offline question bank."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from legal_qa_platform.domain.legal import LegalProvision
from legal_qa_platform.domain.qa import QuestionBankItem
from legal_qa_platform.errors import DataContractError

PROJECT_ROOT = Path.cwd()
DEFAULT_PROVISIONS_PATH = PROJECT_ROOT / "data" / "legal_provisions.json"
DEFAULT_QUESTIONS_PATH = PROJECT_ROOT / "data" / "qa_test_questions.json"
DEFAULT_WARNINGS_PATH = PROJECT_ROOT / "data" / "collection_warnings.json"

_PROVISION_FIELDS = frozenset(
    {
        "provision_id",
        "document_name",
        "chapter_name",
        "section_name",
        "article_no",
        "paragraph_no",
        "subparagraph_no",
        "title",
        "content",
        "search_text",
        "sort_order",
        "source_url",
        "is_active",
    }
)
_QUESTION_FIELDS = frozenset(
    {
        "question_id",
        "question",
        "expected_answer",
        "expected_keywords",
        "expected_provision_ids",
        "document_name",
        "article_no",
    }
)


@dataclass(frozen=True, slots=True)
class DataBundle:
    provisions: tuple[LegalProvision, ...]
    questions: tuple[QuestionBankItem, ...]


def _read_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise DataContractError(f"Required data file is missing: {path.name}") from exc
    except UnicodeDecodeError as exc:
        raise DataContractError(f"Data file is not valid UTF-8: {path.name}") from exc
    except OSError as exc:
        raise DataContractError(f"Data file could not be read: {path.name}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DataContractError(
            f"Data file is not valid JSON: {path.name} line={exc.lineno}"
        ) from exc


def _require_exact_fields(
    item: Any, expected: frozenset[str], index: int
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise DataContractError(f"Data item {index} must be a JSON object.")
    actual = frozenset(str(key) for key in item)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        detail: list[str] = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected))
        raise DataContractError(
            f"Data item {index} has an invalid field set ({'; '.join(detail)})."
        )
    return item


def load_legal_provisions(
    path: Path = DEFAULT_PROVISIONS_PATH,
    *,
    require_full_snapshot: bool = True,
) -> tuple[LegalProvision, ...]:
    payload = _read_json(path)
    if not isinstance(payload, list) or not payload:
        raise DataContractError("Legal provisions must be a non-empty JSON array.")

    provisions: list[LegalProvision] = []
    for index, raw in enumerate(payload, start=1):
        item = _require_exact_fields(raw, _PROVISION_FIELDS, index)
        try:
            provisions.append(LegalProvision.model_validate(item))
        except ValidationError as exc:
            raise DataContractError(
                f"Legal provision {index} violates its schema."
            ) from exc

    ids = [item.provision_id for item in provisions]
    if len(ids) != len(set(ids)):
        raise DataContractError("provision_id values must be unique.")
    stable_keys = [item.stable_key for item in provisions]
    if len(stable_keys) != len(set(stable_keys)):
        raise DataContractError("Canonical stable provision keys must be unique.")
    sort_orders = [item.sort_order for item in provisions]
    if require_full_snapshot and sort_orders != list(range(1, len(provisions) + 1)):
        raise DataContractError(
            "sort_order must be globally ordered and contiguous from 1."
        )
    if not require_full_snapshot and (
        len(sort_orders) != len(set(sort_orders)) or sort_orders != sorted(sort_orders)
    ):
        raise DataContractError(
            "A partial snapshot must contain unique, ascending global "
            "sort_order values."
        )
    if any(not item.is_active for item in provisions):
        raise DataContractError(
            "The publishable seed snapshot may contain current provisions only."
        )
    return tuple(provisions)


def _normalized_unique(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def load_question_bank(
    path: Path = DEFAULT_QUESTIONS_PATH,
    *,
    expected_count: int | None = 100,
) -> tuple[QuestionBankItem, ...]:
    payload = _read_json(path)
    if isinstance(payload, dict) and set(payload) == {"questions"}:
        payload = payload["questions"]
    if not isinstance(payload, list) or not payload:
        raise DataContractError("Question bank must be a non-empty JSON array.")
    if expected_count is not None and len(payload) != expected_count:
        raise DataContractError(
            f"Question bank must contain exactly {expected_count} items."
        )

    questions: list[QuestionBankItem] = []
    for index, raw in enumerate(payload, start=1):
        item = _require_exact_fields(raw, _QUESTION_FIELDS, index)
        try:
            questions.append(QuestionBankItem.model_validate(item))
        except ValidationError as exc:
            raise DataContractError(
                f"Question-bank item {index} violates its schema."
            ) from exc

    ids = [_normalized_unique(item.question_id) for item in questions]
    texts = [_normalized_unique(item.question) for item in questions]
    if len(ids) != len(set(ids)):
        raise DataContractError("Normalized question_id values must be unique.")
    if len(texts) != len(set(texts)):
        raise DataContractError("Normalized question texts must be unique.")
    return tuple(questions)


def validate_question_bank_references(
    questions: tuple[QuestionBankItem, ...],
    provisions: tuple[LegalProvision, ...],
) -> None:
    by_id = {item.provision_id: item for item in provisions}
    for question in questions:
        expected = [
            by_id.get(identifier) for identifier in question.expected_provision_ids
        ]
        if any(item is None for item in expected):
            raise DataContractError(
                f"Question {question.question_id} references an unknown provision."
            )
        primary = expected[0]
        assert primary is not None
        if (
            primary.document_name != question.document_name
            or primary.article_no != question.article_no
        ):
            raise DataContractError(
                f"Question {question.question_id} expected metadata does not "
                "match its provision."
            )
        searchable = _normalized_unique(
            " ".join(
                [question.expected_answer]
                + [item.search_text for item in expected if item is not None]
            )
        )
        if any(
            _normalized_unique(keyword) not in searchable
            for keyword in question.expected_keywords
        ):
            raise DataContractError(
                f"Question {question.question_id} has an unsupported expected keyword."
            )


def load_data_bundle(
    provisions_path: Path = DEFAULT_PROVISIONS_PATH,
    questions_path: Path = DEFAULT_QUESTIONS_PATH,
) -> DataBundle:
    provisions = load_legal_provisions(provisions_path)
    questions = load_question_bank(questions_path)
    validate_question_bank_references(questions, provisions)
    return DataBundle(provisions=provisions, questions=questions)


def load_historical_collection_warnings(
    path: Path = DEFAULT_WARNINGS_PATH,
) -> tuple[dict[str, Any], ...]:
    """Load provenance only; this is intentionally not a publish-gate schema."""

    payload = _read_json(path)
    if not isinstance(payload, list):
        raise DataContractError("Historical warnings must be a JSON array.")
    if any(not isinstance(item, dict) for item in payload):
        raise DataContractError("Every historical warning must be an object.")
    return tuple(dict(item) for item in payload)


__all__ = [
    "DEFAULT_PROVISIONS_PATH",
    "DEFAULT_QUESTIONS_PATH",
    "DEFAULT_WARNINGS_PATH",
    "DataBundle",
    "load_data_bundle",
    "load_historical_collection_warnings",
    "load_legal_provisions",
    "load_question_bank",
    "validate_question_bank_references",
]
