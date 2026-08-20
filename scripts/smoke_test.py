"""Secret-safe live checks for PostgreSQL, Qdrant, and LiteLLM.

The command accepts no credential arguments. It consumes only the documented
process environment through ``RuntimeSettings`` and never prints endpoints,
headers, response bodies, settings, or exception messages.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from time import perf_counter
from typing import Literal, cast

from pydantic import ValidationError

from legal_qa_platform.config import RuntimeSettings
from legal_qa_platform.container import ApplicationContainer
from legal_qa_platform.domain.retrieval import RagContext
from legal_qa_platform.ports.models import ChatMessage
from legal_qa_platform.services.prompt import build_messages, response_schema
from legal_qa_platform.services.validation import parse_structured_response

try:
    from scripts._cli import (
        PROJECT_ROOT,
        print_missing_variables,
        repository_path,
        safe_exception_category,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from _cli import (  # type: ignore[import-not-found, no-redef]
        PROJECT_ROOT,
        print_missing_variables,
        repository_path,
        safe_exception_category,
    )

DEFAULT_PROFILE_PATH = PROJECT_ROOT / "profiles" / "platform-baseline-v1.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run safe live dependency checks.")
    parser.add_argument(
        "--profile",
        default="profiles/platform-baseline-v1.json",
        help="Repository-relative RAG profile path.",
    )
    return parser


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1_000))


async def run_smoke(settings: RuntimeSettings, profile_path: Path) -> int:
    try:
        container = ApplicationContainer.build(
            settings=settings,
            profile_path=profile_path,
        )
    except Exception as exc:
        print(f"[FAIL] composition category={safe_exception_category(exc)}")
        return 1

    failures = 0
    started = perf_counter()
    try:
        await container.open()
        ready = await container.repository.is_ready()
        if ready:
            print(
                "[PASS] PostgreSQL application schema "
                f"latency_ms={_elapsed_ms(started)}"
            )
            started = perf_counter()
            published = await container.repository.has_published_snapshot(
                embedding_model=container.profile.embedding_model,
                embedding_dimension=container.profile.embedding_dimension,
                vector_collection=container.profile.vector_collection,
            )
            if published:
                print(
                    "[PASS] PostgreSQL published snapshot "
                    f"latency_ms={_elapsed_ms(started)}"
                )
            else:
                failures += 1
                print(
                    "[FAIL] PostgreSQL published snapshot missing "
                    f"latency_ms={_elapsed_ms(started)}"
                )
        else:
            failures += 1
            print(
                "[FAIL] PostgreSQL application schema "
                f"latency_ms={_elapsed_ms(started)}"
            )
    except Exception as exc:
        failures += 1
        print(
            "[FAIL] PostgreSQL "
            f"category={safe_exception_category(exc)} latency_ms={_elapsed_ms(started)}"
        )

    qdrant_ready = False
    started = perf_counter()
    try:
        qdrant_ready = await container.qdrant.is_ready()
        if qdrant_ready:
            print(f"[PASS] Qdrant readiness latency_ms={_elapsed_ms(started)}")
        else:
            failures += 1
            print(f"[FAIL] Qdrant readiness latency_ms={_elapsed_ms(started)}")
    except Exception as exc:
        failures += 1
        print(
            "[FAIL] Qdrant readiness "
            f"category={safe_exception_category(exc)} latency_ms={_elapsed_ms(started)}"
        )

    if qdrant_ready:
        started = perf_counter()
        try:
            collection_ready = await container.qdrant.collection_is_ready(
                container.profile.vector_collection,
                dimension=container.profile.embedding_dimension,
            )
            if collection_ready:
                print(
                    "[PASS] Qdrant collection contract "
                    f"dimension={container.profile.embedding_dimension} "
                    f"latency_ms={_elapsed_ms(started)}"
                )
            else:
                failures += 1
                print(
                    "[FAIL] Qdrant collection missing_or_mismatched "
                    f"dimension={container.profile.embedding_dimension} "
                    f"latency_ms={_elapsed_ms(started)}"
                )
        except Exception as exc:
            failures += 1
            print(
                "[FAIL] Qdrant collection contract "
                f"category={safe_exception_category(exc)} "
                f"latency_ms={_elapsed_ms(started)}"
            )

    litellm_ready = False
    started = perf_counter()
    try:
        litellm_ready = await container.litellm.is_ready()
        if litellm_ready:
            print(f"[PASS] LiteLLM readiness latency_ms={_elapsed_ms(started)}")
        else:
            failures += 1
            print(f"[FAIL] LiteLLM readiness latency_ms={_elapsed_ms(started)}")
    except Exception as exc:
        failures += 1
        print(
            "[FAIL] LiteLLM readiness "
            f"category={safe_exception_category(exc)} latency_ms={_elapsed_ms(started)}"
        )

    if litellm_ready:
        started = perf_counter()
        try:
            vectors = await container.litellm.embed(
                ["法規檢索維度驗證"],
                model=container.profile.embedding_model,
                expected_dimension=container.profile.embedding_dimension,
            )
            dimension = len(vectors[0])
            print(
                "[PASS] LiteLLM embedding "
                f"model={container.profile.embedding_model} dimension={dimension} "
                f"latency_ms={_elapsed_ms(started)}"
            )
        except Exception as exc:
            failures += 1
            print(
                "[FAIL] LiteLLM embedding "
                f"category={safe_exception_category(exc)} "
                f"latency_ms={_elapsed_ms(started)}"
            )

        started = perf_counter()
        try:
            question = "若參考條文不足，請以結構化格式說明無法回答。"
            prompt = build_messages(
                question,
                RagContext(question=question, items=[]),
            )
            completion = await container.litellm.complete(
                [
                    ChatMessage(
                        role=cast(Literal["system", "user", "assistant"], item["role"]),
                        content=item["content"],
                    )
                    for item in prompt
                ],
                model=container.profile.chat_model,
                max_tokens=container.profile.chat_max_tokens,
                response_schema=response_schema(),
            )
            parse_structured_response(completion.content)
            print(
                "[PASS] LiteLLM structured chat "
                f"model={container.profile.chat_model} max_tokens=sent "
                f"latency_ms={_elapsed_ms(started)}"
            )
        except Exception as exc:
            failures += 1
            print(
                "[FAIL] LiteLLM structured chat "
                f"category={safe_exception_category(exc)} "
                f"latency_ms={_elapsed_ms(started)}"
            )

    try:
        await container.close()
    except Exception as exc:
        failures += 1
        print(f"[FAIL] dependency shutdown category={safe_exception_category(exc)}")

    if failures:
        print(f"[FAIL] smoke test failed checks={failures}")
        return 1
    print("[PASS] smoke test complete")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        profile_path = repository_path(args.profile, default=DEFAULT_PROFILE_PATH)
        settings = RuntimeSettings()
    except (ValueError, ValidationError):
        print("[FAIL] runtime configuration is invalid; check documented types.")
        return 2
    missing = settings.missing_for_runtime()
    if missing:
        print_missing_variables(missing, command="python scripts/smoke_test.py")
        return 2
    return asyncio.run(run_smoke(settings, profile_path))


if __name__ == "__main__":
    raise SystemExit(main())
