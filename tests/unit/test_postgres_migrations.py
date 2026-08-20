from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from scripts import migrate

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIRECTORY = PROJECT_ROOT / "migrations"
POSTCHECK = MIGRATIONS_DIRECTORY / "checks" / "0001_initial_readonly.sql"


_VALID_SQL_TEMPLATE = """-- migration-version: __FILENAME__
BEGIN;
CREATE SCHEMA IF NOT EXISTS legal_qa;
CREATE TABLE IF NOT EXISTS legal_qa.schema_migrations (
    version text PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS legal_qa.example (
    example_id bigint PRIMARY KEY
);
INSERT INTO legal_qa.example (example_id)
VALUES (1)
ON CONFLICT (example_id) DO NOTHING;
INSERT INTO legal_qa.schema_migrations (version)
VALUES ('__FILENAME__')
ON CONFLICT (version) DO NOTHING;
COMMIT;
"""


def _valid_sql(filename: str = "0001_example.sql") -> str:
    return _VALID_SQL_TEMPLATE.replace("__FILENAME__", filename)


def test_checked_in_manual_bundle_is_valid_and_history_is_transactional() -> None:
    migrations = migrate.validate_migration_bundle(MIGRATIONS_DIRECTORY)
    postcheck_digest = migrate.validate_read_only_postcheck(POSTCHECK)
    sql_text = (MIGRATIONS_DIRECTORY / "0001_initial.sql").read_text(encoding="utf-8")
    normalized = " ".join(sql_text.split())

    assert [item.filename for item in migrations] == ["0001_initial.sql"]
    assert len(migrations[0].sha256) == 64
    assert len(postcheck_digest) == 64
    assert normalized.startswith("-- migration-version: 0001_initial.sql")
    assert "BEGIN;" in normalized
    assert normalized.endswith("COMMIT;")
    assert normalized.index("CREATE TABLE IF NOT EXISTS legal_qa.feedback") < (
        normalized.index("INSERT INTO legal_qa.schema_migrations (version)")
    )
    assert "VALUES ('0001_initial.sql')" in normalized


def test_offline_handoff_does_not_import_runtime_or_database_clients(
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = inspect.getsource(migrate)

    assert "RuntimeSettings" not in source
    assert "PostgresMigrationSettings" not in source
    assert "create_postgres" not in source
    assert "psycopg" not in source
    assert "run_async" not in source
    direct_environment_access = "".join(("os.", "environ"))
    assert direct_environment_access not in source

    exit_code = migrate.main([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[PASS] offline migration bundle validated" in output
    assert "database_unchanged=true" in output
    assert "[HANDOFF] DBeaver" in output
    assert "No database connection was attempted" in output
    assert "POSTGRES_" not in output


@pytest.mark.parametrize(
    "option",
    (
        "--endpoint-scope",
        "--api-key",
        "--password",
        "--admin-user",
        "--database",
    ),
)
def test_offline_handoff_rejects_connection_and_credential_options(option: str) -> None:
    with pytest.raises(SystemExit):
        migrate.build_parser().parse_args([option, "unit-test-value"])


@pytest.mark.parametrize(
    ("unsafe_sql", "category"),
    [
        (
            "GRANT SELECT ON legal_qa.example TO application_role;",
            "migration_contains_prohibited_sql",
        ),
        (
            "CREATE ROLE application_role;",
            "migration_contains_prohibited_sql",
        ),
        (
            "DROP TABLE legal_qa.example;",
            "migration_contains_prohibited_sql",
        ),
        (
            "CREATE TABLE <RUNTIME_TABLE> (id bigint);",
            "migration_contains_prohibited_sql",
        ),
    ],
)
def test_manual_bundle_rejects_privilege_destructive_and_placeholder_sql(
    unsafe_sql: str,
    category: str,
) -> None:
    sql_text = _valid_sql().replace(
        "INSERT INTO legal_qa.schema_migrations (version)",
        f"{unsafe_sql}\nINSERT INTO legal_qa.schema_migrations (version)",
    )
    with pytest.raises(migrate.MigrationBundleError) as caught:
        migrate._validate_migration_sql("0001_example.sql", sql_text)

    assert caught.value.category == category


@pytest.mark.parametrize(
    "outside_sql",
    (
        "ALTER TABLE litellm.audit_log ADD COLUMN extra text;",
        (
            "INSERT INTO public.application_data (record_id) VALUES (1) "
            "ON CONFLICT (record_id) DO NOTHING;"
        ),
        "CREATE TABLE IF NOT EXISTS other_schema.shadow (record_id bigint);",
        "CREATE INDEX IF NOT EXISTS shadow_idx ON public.shadow (record_id);",
    ),
)
def test_manual_bundle_rejects_mutation_targets_outside_legal_qa(
    outside_sql: str,
) -> None:
    sql_text = _valid_sql().replace(
        "INSERT INTO legal_qa.schema_migrations (version)",
        f"{outside_sql}\nINSERT INTO legal_qa.schema_migrations (version)",
    )

    with pytest.raises(migrate.MigrationBundleError) as caught:
        migrate._validate_migration_sql("0001_example.sql", sql_text)

    assert caught.value.category == "migration_target_outside_legal_qa"


def test_manual_bundle_requires_history_as_last_statement_before_commit() -> None:
    sql_text = _valid_sql().replace(
        "ON CONFLICT (version) DO NOTHING;\nCOMMIT;",
        "ON CONFLICT (version) DO NOTHING;\nSELECT 1;\nCOMMIT;",
    )
    with pytest.raises(migrate.MigrationBundleError) as caught:
        migrate._validate_migration_sql("0001_example.sql", sql_text)

    assert caught.value.category == "migration_history_contract_invalid"


def test_manual_bundle_requires_repeatable_insert_and_create() -> None:
    unsafe_insert = _valid_sql().replace(
        "ON CONFLICT (example_id) DO NOTHING;",
        "RETURNING example_id;",
    )
    with pytest.raises(migrate.MigrationBundleError) as caught:
        migrate._validate_migration_sql("0001_example.sql", unsafe_insert)
    assert caught.value.category == "migration_insert_not_repeatable"

    unsafe_create = _valid_sql().replace(
        "CREATE TABLE IF NOT EXISTS legal_qa.example",
        "CREATE TABLE legal_qa.example",
    )
    with pytest.raises(migrate.MigrationBundleError) as caught:
        migrate._validate_migration_sql("0001_example.sql", unsafe_create)
    assert caught.value.category == "migration_create_not_repeatable"


def test_postcheck_validator_rejects_mutation() -> None:
    postcheck_sql = (
        "SELECT '0001_initial.sql';\nUPDATE legal_qa.feedback SET rating = 1;\n"
    )

    with pytest.raises(migrate.MigrationBundleError) as caught:
        migrate._validate_read_only_postcheck_sql(postcheck_sql)

    assert caught.value.category == "postcheck_not_read_only"
