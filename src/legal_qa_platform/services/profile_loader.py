"""Load the single checked-in baseline profile without environment magic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.errors import DataContractError

PROJECT_ROOT = Path.cwd()
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "profiles" / "platform-baseline-v1.json"


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> RagProfile:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DataContractError(f"RAG profile is missing: {path.name}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataContractError(f"RAG profile is invalid: {path.name}") from exc
    try:
        return RagProfile.model_validate(payload)
    except ValidationError as exc:
        raise DataContractError(
            f"RAG profile violates its schema: {path.name}"
        ) from exc


__all__ = ["DEFAULT_PROFILE_PATH", "load_profile"]
