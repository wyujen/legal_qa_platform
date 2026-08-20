"""Apply repeatable application-owned PostgreSQL migrations.

Credentials are accepted only through ``RuntimeSettings``. This command has no
credential flags and reports only documented missing variable names or safe
failure categories.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError

from legal_qa_platform.adapters.postgres import (
    PostgresRepository,
    create_postgres_pool,
)
from legal_qa_platform.async_runtime import run_async
from legal_qa_platform.config import RuntimeSettings

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply legal_qa_platform application-schema migrations."
    )
    parser.add_argument(
        "--migrations-dir",
        default="migrations",
        help="Repository-relative migration directory (default: migrations).",
    )
    return parser


async def run_migrations(settings: RuntimeSettings, migrations: Path) -> int:
    repository = PostgresRepository(create_postgres_pool(settings))
    opened = False
    try:
        await repository.open()
        opened = True
        applied = await repository.apply_migrations(migrations)
    except Exception as exc:
        print(f"[FAIL] PostgreSQL migration category={safe_exception_category(exc)}")
        return 1
    finally:
        if opened:
            await repository.close()

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
        migrations = repository_path(
            args.migrations_dir,
            default=PROJECT_ROOT / "migrations",
        )
        settings = RuntimeSettings()
    except (ValueError, ValidationError):
        print("[FAIL] migration configuration is invalid; check documented types.")
        return 2

    missing = settings.missing_for_postgres()
    if missing:
        print_missing_variables(missing, command="python scripts/migrate.py")
        return 2
    return run_async(run_migrations(settings, migrations))


if __name__ == "__main__":
    raise SystemExit(main())
