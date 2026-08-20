"""Validate the manual PostgreSQL migration handoff without connecting to a DB.

The Human Operator executes the checked-in SQL with DBeaver. This command reads
only repository files, accepts no endpoint or credential inputs, performs no
network calls, and never claims that a database migration was applied.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from scripts._cli import PROJECT_ROOT
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from _cli import PROJECT_ROOT  # type: ignore[import-not-found, no-redef]

MIGRATIONS_DIRECTORY = PROJECT_ROOT / "migrations"
READ_ONLY_POSTCHECK = MIGRATIONS_DIRECTORY / "checks" / "0001_initial_readonly.sql"
_MIGRATION_FILENAME = re.compile(r"^(?P<sequence>\d{4})_[a-z0-9_]+\.sql$")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\r\n]*")
_PROHIBITED_MIGRATION_PATTERNS = (
    re.compile(r"\b(?:CREATE|ALTER|DROP)\s+(?:ROLE|USER|DATABASE)\b", re.IGNORECASE),
    re.compile(r"\b(?:GRANT|REVOKE)\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+(?:SCHEMA|TABLE|SEQUENCE|INDEX|EXTENSION)\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
    re.compile(r"\bALTER\s+TABLE\b[^;]*\bDROP\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bCREATE\s+EXTENSION\b", re.IGNORECASE),
    re.compile(r"\bSET\s+(?:ROLE|SESSION\s+AUTHORIZATION)\b", re.IGNORECASE),
    re.compile(r"\\(?:connect|c|include|i)\b", re.IGNORECASE),
    re.compile(r"(?:\$\{|\{\{|<[A-Z][A-Z0-9_]*>)"),
)
_POSTCHECK_MUTATION = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|CALL|DO|COPY)\b",
    re.IGNORECASE,
)
_SQL_IDENTIFIER = r'(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_$]*)'
_QUALIFIED_TARGET = rf"{_SQL_IDENTIFIER}(?:\s*\.\s*{_SQL_IDENTIFIER})?"
_SCHEMA_OBJECT_TARGETS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        rf"\bCREATE\s+(?:TABLE|SEQUENCE|VIEW|MATERIALIZED\s+VIEW|TYPE|FUNCTION|PROCEDURE)\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<target>{_QUALIFIED_TARGET})",
        rf"\bALTER\s+(?:TABLE|SEQUENCE|VIEW|MATERIALIZED\s+VIEW|TYPE|FUNCTION|PROCEDURE|INDEX)\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?P<target>{_QUALIFIED_TARGET})",
        rf"\bDROP\s+(?:TABLE|SEQUENCE|VIEW|MATERIALIZED\s+VIEW|TYPE|FUNCTION|PROCEDURE|INDEX)\s+(?:IF\s+EXISTS\s+)?(?P<target>{_QUALIFIED_TARGET})",
        rf"\bINSERT\s+INTO\s+(?P<target>{_QUALIFIED_TARGET})",
        rf"\bUPDATE\s+(?:ONLY\s+)?(?P<target>{_QUALIFIED_TARGET})",
        rf"\bDELETE\s+FROM\s+(?:ONLY\s+)?(?P<target>{_QUALIFIED_TARGET})",
        rf"\bMERGE\s+INTO\s+(?P<target>{_QUALIFIED_TARGET})",
        rf"\bTRUNCATE(?:\s+TABLE)?\s+(?:ONLY\s+)?(?P<target>{_QUALIFIED_TARGET})",
        rf"\bCOPY\s+(?P<target>{_QUALIFIED_TARGET})",
    )
)
_CREATE_INDEX_TARGET = re.compile(
    rf"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"(?P<index>{_QUALIFIED_TARGET})\s+ON\s+(?:ONLY\s+)?"
    rf"(?P<target>{_QUALIFIED_TARGET})",
    re.IGNORECASE,
)


class MigrationBundleError(ValueError):
    """A bounded offline validation failure with a safe public category."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


@dataclass(frozen=True, slots=True)
class ValidatedMigration:
    """Safe handoff metadata for one checked-in SQL migration."""

    filename: str
    sha256: str


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Validate the offline DBeaver SQL handoff. This command does not "
            "connect to or modify PostgreSQL."
        )
    )


def _without_comments(sql_text: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", sql_text))


def _read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MigrationBundleError("sql_file_unreadable") from exc


def _ordered_migration_paths(directory: Path) -> tuple[Path, ...]:
    try:
        paths = sorted(path for path in directory.glob("*.sql") if path.is_file())
    except OSError as exc:
        raise MigrationBundleError("migration_directory_unreadable") from exc
    if not paths:
        raise MigrationBundleError("migration_bundle_empty")

    sequences: list[int] = []
    for path in paths:
        match = _MIGRATION_FILENAME.fullmatch(path.name)
        if match is None:
            raise MigrationBundleError("migration_filename_invalid")
        sequences.append(int(match.group("sequence")))
    if sequences != list(range(1, len(sequences) + 1)):
        raise MigrationBundleError("migration_sequence_invalid")
    return tuple(paths)


def _validate_repeatable_inserts(sql_without_comments: str) -> None:
    for match in re.finditer(
        r"\bINSERT\s+INTO\b.*?;",
        sql_without_comments,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        if re.search(r"\bON\s+CONFLICT\b", match.group(0), re.IGNORECASE) is None:
            raise MigrationBundleError("migration_insert_not_repeatable")


def _normalized_sql_identifier(value: str) -> str:
    return re.sub(r'["\s]', "", value).casefold()


def _validate_schema_targets(sql_without_comments: str) -> None:
    schema_creates = re.finditer(
        rf"\bCREATE\s+SCHEMA\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        rf"(?P<target>{_SQL_IDENTIFIER})",
        sql_without_comments,
        re.IGNORECASE,
    )
    for match in schema_creates:
        if _normalized_sql_identifier(match.group("target")) != "legal_qa":
            raise MigrationBundleError("migration_target_outside_legal_qa")

    for pattern in _SCHEMA_OBJECT_TARGETS:
        for match in pattern.finditer(sql_without_comments):
            target = _normalized_sql_identifier(match.group("target"))
            if not target.startswith("legal_qa."):
                raise MigrationBundleError("migration_target_outside_legal_qa")

    for match in _CREATE_INDEX_TARGET.finditer(sql_without_comments):
        index = _normalized_sql_identifier(match.group("index"))
        target = _normalized_sql_identifier(match.group("target"))
        if "." in index and not index.startswith("legal_qa."):
            raise MigrationBundleError("migration_target_outside_legal_qa")
        if not target.startswith("legal_qa."):
            raise MigrationBundleError("migration_target_outside_legal_qa")


def _validate_migration_sql(filename: str, sql_text: str) -> ValidatedMigration:
    marker = f"-- migration-version: {filename}"
    if marker not in sql_text.splitlines()[:5]:
        raise MigrationBundleError("migration_version_marker_invalid")

    sql_without_comments = _without_comments(sql_text).strip()
    if re.match(r"^BEGIN\s*;", sql_without_comments, re.IGNORECASE) is None:
        raise MigrationBundleError("migration_transaction_missing")
    if re.search(r"COMMIT\s*;\s*$", sql_without_comments, re.IGNORECASE) is None:
        raise MigrationBundleError("migration_transaction_missing")
    if len(re.findall(r"\bBEGIN\s*;", sql_without_comments, re.IGNORECASE)) != 1:
        raise MigrationBundleError("migration_transaction_invalid")
    if len(re.findall(r"\bCOMMIT\s*;", sql_without_comments, re.IGNORECASE)) != 1:
        raise MigrationBundleError("migration_transaction_invalid")

    _validate_schema_targets(sql_without_comments)
    for pattern in _PROHIBITED_MIGRATION_PATTERNS:
        if pattern.search(sql_without_comments):
            raise MigrationBundleError("migration_contains_prohibited_sql")

    unsafe_create = re.search(
        r"\bCREATE\s+(?:SCHEMA|SEQUENCE|TABLE|(?:UNIQUE\s+)?INDEX)\s+"
        r"(?!IF\s+NOT\s+EXISTS\b)",
        sql_without_comments,
        re.IGNORECASE,
    )
    if unsafe_create is not None:
        raise MigrationBundleError("migration_create_not_repeatable")
    _validate_repeatable_inserts(sql_without_comments)

    history_table = re.search(
        r"\bCREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+"
        r"legal_qa\.schema_migrations\b",
        sql_without_comments,
        re.IGNORECASE,
    )
    escaped_filename = re.escape(filename)
    history_at_end = re.search(
        r"INSERT\s+INTO\s+legal_qa\.schema_migrations\s*"
        r"\(\s*version\s*\)\s*"
        rf"VALUES\s*\(\s*'{escaped_filename}'\s*\)\s*"
        r"ON\s+CONFLICT\s*\(\s*version\s*\)\s+DO\s+NOTHING\s*;\s*"
        r"COMMIT\s*;\s*$",
        sql_without_comments,
        re.IGNORECASE | re.DOTALL,
    )
    if history_table is None or history_at_end is None:
        raise MigrationBundleError("migration_history_contract_invalid")
    if history_table.start() > history_at_end.start():
        raise MigrationBundleError("migration_history_contract_invalid")

    return ValidatedMigration(
        filename=filename,
        sha256=hashlib.sha256(sql_text.encode("utf-8")).hexdigest(),
    )


def _validate_migration(path: Path) -> ValidatedMigration:
    return _validate_migration_sql(path.name, _read_utf8(path))


def _validate_read_only_postcheck_sql(sql_text: str) -> str:
    sql_without_comments = _without_comments(sql_text).strip()
    if not re.match(r"^(?:WITH|SELECT)\b", sql_without_comments, re.IGNORECASE):
        raise MigrationBundleError("postcheck_not_read_only")
    if _POSTCHECK_MUTATION.search(sql_without_comments):
        raise MigrationBundleError("postcheck_not_read_only")
    if "0001_initial.sql" not in sql_without_comments:
        raise MigrationBundleError("postcheck_history_contract_invalid")
    return hashlib.sha256(sql_text.encode("utf-8")).hexdigest()


def validate_read_only_postcheck(path: Path = READ_ONLY_POSTCHECK) -> str:
    """Validate and return the post-check digest without executing its SQL."""

    return _validate_read_only_postcheck_sql(_read_utf8(path))


def validate_migration_bundle(
    directory: Path = MIGRATIONS_DIRECTORY,
) -> tuple[ValidatedMigration, ...]:
    """Validate ordered, transactional, repeatable SQL without any DB access."""

    return tuple(
        _validate_migration(path) for path in _ordered_migration_paths(directory)
    )


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    try:
        migrations = validate_migration_bundle()
        postcheck_sha256 = validate_read_only_postcheck()
    except MigrationBundleError as exc:
        print(f"[FAIL] offline migration bundle category={exc.category}")
        print("[INFO] database_unchanged=true")
        return 1

    print(
        "[PASS] offline migration bundle validated "
        f"files={len(migrations)} database_unchanged=true"
    )
    for migration in migrations:
        print(f"  - migrations/{migration.filename} sha256={migration.sha256}")
    print(
        "[PASS] read-only post-check validated "
        f"path=migrations/checks/0001_initial_readonly.sql sha256={postcheck_sha256}"
    )
    print(
        "[HANDOFF] DBeaver: run each migration above in order with "
        "Execute SQL Script; do not execute selected statements individually."
    )
    print(
        "[HANDOFF] After COMMIT, run migrations/checks/0001_initial_readonly.sql; "
        "every returned passed value must be true."
    )
    print("[INFO] No database connection was attempted; no migration was applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
