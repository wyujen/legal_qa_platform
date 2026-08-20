"""Synchronize a validated legal snapshot into PostgreSQL and Qdrant."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal, cast

from pydantic import ValidationError

from legal_qa_platform.async_runtime import run_async
from legal_qa_platform.config import RuntimeSettings
from legal_qa_platform.container import ApplicationContainer
from legal_qa_platform.services.data_loader import load_legal_provisions
from legal_qa_platform.services.ingestion import IngestionService

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

DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "legal_provisions.json"
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "profiles" / "platform-baseline-v1.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize legal master data and its Qdrant projection."
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("full-snapshot", "partial"),
        help="Use full-snapshot only for a complete authoritative input.",
    )
    parser.add_argument(
        "--data",
        default="data/legal_provisions.json",
        help="Repository-relative provision JSON path.",
    )
    parser.add_argument(
        "--profile",
        default="profiles/platform-baseline-v1.json",
        help="Repository-relative RAG profile path.",
    )
    parser.add_argument(
        "--confirm-authoritative-full-snapshot",
        action="store_true",
        help=(
            "Required when full-snapshot uses a non-default data file; confirms "
            "that absent provisions should be retired."
        ),
    )
    return parser


async def synchronize(
    *,
    settings: RuntimeSettings,
    data_path: Path,
    profile_path: Path,
    mode: Literal["full_snapshot", "partial"],
) -> int:
    try:
        provisions = load_legal_provisions(
            data_path,
            require_full_snapshot=mode == "full_snapshot",
        )
        container = ApplicationContainer.build(
            settings=settings,
            profile_path=profile_path,
        )
    except Exception as exc:
        print(f"[FAIL] synchronization setup category={safe_exception_category(exc)}")
        return 1

    service = IngestionService(
        repository=container.repository,
        vector_store=container.qdrant,
        embeddings=container.litellm,
        profile=container.profile,
    )
    try:
        await container.open()
        summary = await service.sync(
            provisions,
            mode=mode,
            source_label=data_path.relative_to(PROJECT_ROOT).as_posix(),
        )
    except Exception as exc:
        print(f"[FAIL] synchronization category={safe_exception_category(exc)}")
        return 1
    finally:
        await container.close()

    print(
        "[PASS] legal synchronization "
        f"run_id={summary.run_id} generation={summary.generation} "
        f"provisions={summary.provision_count} embedded={summary.embedded_count} "
        f"reused={summary.reused_vector_count} "
        f"deactivated={summary.deactivated_count}"
    )
    if summary.qdrant_cleanup_pending:
        print(
            "[WARN] Qdrant retirement payload cleanup is pending; "
            "PostgreSQL is current."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data_path = repository_path(args.data, default=DEFAULT_DATA_PATH)
        profile_path = repository_path(args.profile, default=DEFAULT_PROFILE_PATH)
        settings = RuntimeSettings()
    except (ValueError, ValidationError):
        print(
            "[FAIL] synchronization configuration is invalid; check documented types."
        )
        return 2

    if (
        args.mode == "full-snapshot"
        and data_path != DEFAULT_DATA_PATH.resolve()
        and not args.confirm_authoritative_full_snapshot
    ):
        print(
            "[FAIL] non-default full snapshot requires "
            "--confirm-authoritative-full-snapshot."
        )
        return 2

    missing = settings.missing_for_runtime()
    if missing:
        print_missing_variables(
            missing,
            command=f"python scripts/sync_laws.py --mode {args.mode}",
        )
        return 2

    mode = cast(Literal["full_snapshot", "partial"], args.mode.replace("-", "_"))
    return run_async(
        synchronize(
            settings=settings,
            data_path=data_path,
            profile_path=profile_path,
            mode=mode,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
