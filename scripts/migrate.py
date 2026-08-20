"""Apply repeatable application-owned PostgreSQL migrations.

This explicit operator command uses ``POSTGRES_ADMIN_*`` only for migration and
grants the existing ``POSTGRES_LITELLM_USER`` least runtime privileges. It never
creates or alters roles/databases, has no credential flags, and reports only
documented variable names or safe failure categories.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from legal_qa_platform.adapters.postgres import (
    create_postgres_migration_runner,
)
from legal_qa_platform.async_runtime import run_async
from legal_qa_platform.config import PostgresMigrationSettings
from legal_qa_platform.errors import ConfigurationError

try:
    from scripts._cli import (
        PROJECT_ROOT,
        print_missing_variables,
        safe_exception_category,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from _cli import (  # type: ignore[import-not-found, no-redef]
        PROJECT_ROOT,
        print_missing_variables,
        safe_exception_category,
    )

EndpointScope = Literal["auto", "public", "internal"]
MIGRATIONS_DIRECTORY = PROJECT_ROOT / "migrations"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Apply legal_qa_platform migrations with the operator-only "
            "PostgreSQL identity."
        )
    )
    parser.add_argument(
        "--endpoint-scope",
        choices=("auto", "public", "internal"),
        default="auto",
        help=(
            "Select the PostgreSQL endpoint family. 'auto' preserves runtime "
            "precedence; 'public' selects POSTGRES_EXTERNAL_HOST."
        ),
    )
    return parser


def select_postgres_endpoint_scope(
    settings: PostgresMigrationSettings,
    scope: EndpointScope,
) -> PostgresMigrationSettings:
    """Select one existing host field without changing runtime precedence."""

    if scope == "auto":
        return settings
    if scope == "public":
        return settings.model_copy(update={"postgres_internal_host": None})
    return settings.model_copy(update={"postgres_external_host": None})


def _missing_for_scope(
    settings: PostgresMigrationSettings,
    scope: EndpointScope,
) -> tuple[str, ...]:
    """Use a precise host name for an explicitly selected endpoint family."""

    missing = list(settings.missing_for_migration())
    generic = "POSTGRES_INTERNAL_HOST or POSTGRES_EXTERNAL_HOST"
    if generic in missing and scope != "auto":
        missing[missing.index(generic)] = (
            "POSTGRES_EXTERNAL_HOST" if scope == "public" else "POSTGRES_INTERNAL_HOST"
        )
    return tuple(missing)


async def run_migrations(
    settings: PostgresMigrationSettings,
    migrations: Path,
) -> int:
    try:
        runner = create_postgres_migration_runner(settings)
    except Exception as exc:
        print(
            "[FAIL] PostgreSQL migration composition "
            f"category={safe_exception_category(exc)}"
        )
        return 1
    opened = False
    applied: tuple[str, ...] = ()
    migration_failure: str | None = None
    close_failure: str | None = None
    try:
        await runner.open()
        opened = True
        applied = await runner.apply_migrations(migrations)
    except Exception as exc:
        migration_failure = safe_exception_category(exc)
    finally:
        if opened:
            try:
                await runner.close()
            except Exception as exc:
                close_failure = safe_exception_category(exc)

    if migration_failure is not None:
        print(f"[FAIL] PostgreSQL migration category={migration_failure}")
        return 1
    if close_failure is not None:
        print(f"[FAIL] PostgreSQL migration shutdown category={close_failure}")
        return 1

    if applied:
        print(f"[PASS] PostgreSQL migrations applied count={len(applied)}")
        for name in applied:
            print(f"  - {name}")
    else:
        print("[PASS] PostgreSQL schema is current; applied count=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = select_postgres_endpoint_scope(
            PostgresMigrationSettings(),
            args.endpoint_scope,
        )
    except ValidationError:
        print("[FAIL] migration configuration is invalid; check documented types.")
        return 2

    endpoint_family = (
        "internal"
        if settings.postgres_internal_host
        else "external"
        if settings.postgres_external_host
        else "missing"
    )
    print(
        "[INFO] migration endpoint selection "
        f"scope={args.endpoint_scope} postgres={endpoint_family}"
    )
    missing = _missing_for_scope(settings, args.endpoint_scope)
    if missing:
        command = "python scripts/migrate.py"
        if args.endpoint_scope != "auto":
            command = f"{command} --endpoint-scope {args.endpoint_scope}"
        print_missing_variables(missing, command=command)
        return 2
    try:
        settings.require_migration()
    except ConfigurationError:
        print("[FAIL] migration configuration category=identity_contract_invalid")
        return 2
    return run_async(run_migrations(settings, MIGRATIONS_DIRECTORY))


if __name__ == "__main__":
    raise SystemExit(main())
