"""Export deterministic JSON Schemas for checked-in domain and REST contracts."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import BaseModel

from legal_qa_platform.api.schemas import (
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    ReadinessResponse,
    RetrieveRequest,
    RetrieveResponse,
)
from legal_qa_platform.domain.legal import LegalProvision
from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.domain.qa import (
    ChatRequest,
    ChatResponse,
    LegalQaResponse,
    LLMAnswer,
    QuestionBankItem,
)
from legal_qa_platform.domain.retrieval import ContextItem, RagContext, RetrievalResult

try:
    from scripts._cli import PROJECT_ROOT, repository_output_path, write_json
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from _cli import (  # type: ignore[import-not-found, no-redef]
        PROJECT_ROOT,
        repository_output_path,
        write_json,
    )


def schema_models() -> dict[str, type[BaseModel]]:
    """Return the stable filename-to-model export catalog."""

    return {
        "chat_request": ChatRequest,
        "chat_response": ChatResponse,
        "context_item": ContextItem,
        "error_response": ErrorResponse,
        "feedback_request": FeedbackRequest,
        "feedback_response": FeedbackResponse,
        "health_response": HealthResponse,
        "legal_provision": LegalProvision,
        "legal_qa_response": LegalQaResponse,
        "llm_answer": LLMAnswer,
        "question_bank_item": QuestionBankItem,
        "rag_context": RagContext,
        "rag_profile": RagProfile,
        "readiness_response": ReadinessResponse,
        "retrieval_result": RetrievalResult,
        "retrieve_request": RetrieveRequest,
        "retrieve_response": RetrieveResponse,
    }


def export_schemas(output_directory: Path) -> tuple[Path, ...]:
    output_directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in sorted(schema_models().items()):
        path = output_directory / f"{name}.schema.json"
        write_json(path, model.model_json_schema(mode="validation"))
        written.append(path)
    return tuple(written)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export versioned Pydantic schemas.")
    parser.add_argument(
        "--output-dir",
        default="schemas",
        help="Repository-relative schema directory (default: schemas).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output_directory = repository_output_path(
            args.output_dir,
            default=PROJECT_ROOT / "schemas",
        )
        written = export_schemas(output_directory)
    except Exception as exc:
        print(f"[FAIL] schema export category={type(exc).__name__}")
        return 1
    relative = output_directory.relative_to(PROJECT_ROOT).as_posix()
    print(f"[PASS] schema export files={len(written)} directory={relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
