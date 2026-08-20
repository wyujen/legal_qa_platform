from __future__ import annotations

import re
from pathlib import Path

from legal_qa_platform.services.data_loader import load_data_bundle

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_checked_in_legal_snapshot_and_question_bank_are_complete() -> None:
    bundle = load_data_bundle(
        PROJECT_ROOT / "data" / "legal_provisions.json",
        PROJECT_ROOT / "data" / "qa_test_questions.json",
    )

    assert len(bundle.provisions) == 2_234
    assert [item.provision_id for item in bundle.provisions] == list(range(9, 2_243))
    assert [item.sort_order for item in bundle.provisions] == list(range(1, 2_235))
    assert all(item.is_active for item in bundle.provisions)
    assert len({item.stable_key for item in bundle.provisions}) == 2_234

    assert len(bundle.questions) == 100
    assert [item.question_id for item in bundle.questions] == [
        f"Q{index:03d}" for index in range(1, 101)
    ]
    provision_ids = {item.provision_id for item in bundle.provisions}
    assert all(
        set(question.expected_provision_ids) <= provision_ids
        for question in bundle.questions
    )


def test_initial_migration_reserves_legacy_ids_and_contains_no_vector_storage() -> None:
    migration = (PROJECT_ROOT / "migrations" / "0001_initial.sql").read_text(
        encoding="utf-8"
    )
    lowered = migration.casefold()

    assert "generate_series(1, 8)" in migration
    assert "reserved_legacy" in migration
    assert "provision_identity_ledger" in migration
    assert "pgvector" not in lowered
    assert not re.search(r"\bcreate\s+extension\b[^;]*\bvector\b", lowered)
    assert not re.search(r"\bvector\s*\(", lowered)
    assert "legal_qa.qa_runs" in migration
    assert "legal_qa.conversations" in migration
