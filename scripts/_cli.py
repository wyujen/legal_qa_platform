"""Shared, secret-safe helpers for repository scripts.

This module never inspects the process environment. Runtime settings remain
owned by their typed settings model so commands cannot accidentally widen the
environment-variable boundary. Manual migration validation reads repository
SQL only and does not use this module for database configuration.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from legal_qa_platform.errors import ExternalServiceError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SAFE_CATEGORY = re.compile(r"[^a-zA-Z0-9_.:-]+")


def utc_run_stamp() -> str:
    """Return a filesystem-safe UTC timestamp."""

    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def repository_path(value: str | None, *, default: Path) -> Path:
    """Resolve a path and reject references outside this repository."""

    candidate = default if value is None else Path(value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("Output path must stay inside the repository.") from exc
    return resolved


def repository_output_path(value: str | None, *, default: Path) -> Path:
    """Resolve an output path and reject writes outside this repository."""

    return repository_path(value, default=default)


def write_json(path: Path, payload: Any) -> None:
    """Write deterministic UTF-8 JSON through an atomic same-directory rename."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def percentile(values: list[float], quantile: float) -> float | None:
    """Return a linearly interpolated percentile, or ``None`` for no samples."""

    if not values:
        return None
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def latency_summary(values: list[float]) -> dict[str, float | None]:
    """Summarize allowlisted timings without retaining request content."""

    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def safe_exception_category(exc: BaseException) -> str:
    """Return only a bounded error class/category, never an exception message."""

    if isinstance(exc, ExternalServiceError):
        raw = f"{exc.service}:{exc.category}"
    else:
        raw = type(exc).__name__
    cleaned = _SAFE_CATEGORY.sub("_", raw)[:100]
    return cleaned or "unknown"


def print_missing_variables(names: tuple[str, ...], *, command: str) -> None:
    """Print names and a safe retry command, with no values or source details."""

    print("[SKIP] required runtime environment variable names are missing:")
    for name in names:
        print(f"  - {name}")
    print("Human Operator: inject these variables into the current process, then run:")
    print(f"  {command}")


__all__ = [
    "PROJECT_ROOT",
    "latency_summary",
    "percentile",
    "print_missing_variables",
    "repository_output_path",
    "repository_path",
    "safe_exception_category",
    "utc_run_stamp",
    "write_json",
]
