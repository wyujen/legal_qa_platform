from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts._cli import PROJECT_ROOT  # noqa: E402
from scripts.export_schemas import schema_models  # noqa: E402
from scripts.verify_repository import (  # noqa: E402
    _scan_secret_material,
    run_verification,
)


def test_repository_verification_passes_current_tree() -> None:
    findings, stats = run_verification(PROJECT_ROOT)

    assert findings == []
    assert stats == {"provisions": 2234, "documents": 223, "questions": 100}


def test_checked_in_json_schemas_match_pydantic_models() -> None:
    for name, model in schema_models().items():
        path = PROJECT_ROOT / "schemas" / f"{name}.schema.json"
        actual = json.loads(path.read_text(encoding="utf-8"))
        assert actual == model.model_json_schema(mode="validation")


def test_secret_scan_reports_location_without_echoing_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = PROJECT_ROOT / "src" / "synthetic_secret_scan_fixture.py"
    sensitive_literal = "constructed-looking-credential-1234567890"
    source_payload = f'api_key = "{sensitive_literal}"\n'  # test-only fixture
    original_read_text = Path.read_text

    def fake_read_text(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if path == source:
            return source_payload
        return original_read_text(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    findings = _scan_secret_material(PROJECT_ROOT, [source])

    assert len(findings) == 1
    assert findings[0].rule == "credential_literal_assignment"
    assert findings[0].path == "src/synthetic_secret_scan_fixture.py"
    assert findings[0].line == 1
    assert sensitive_literal not in repr(findings[0])
