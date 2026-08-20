"""Offline repository independence, data, and secret-safety verification.

Findings deliberately contain only a rule identifier, repository-relative path,
and line number. Suspicious matched text is never echoed.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from pydantic import SecretStr

from legal_qa_platform import __version__
from legal_qa_platform.config.settings import (
    DOCUMENTED_ENVIRONMENT_VARIABLES,
    POSTGRES_MIGRATION_ENVIRONMENT_VARIABLES,
    RUNTIME_ENVIRONMENT_VARIABLES,
    PostgresMigrationSettings,
    RuntimeSettings,
)
from legal_qa_platform.services.data_loader import load_data_bundle
from legal_qa_platform.services.profile_loader import load_profile

try:
    from scripts._cli import PROJECT_ROOT, repository_path
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from _cli import (  # type: ignore[import-not-found, no-redef]
        PROJECT_ROOT,
        repository_path,
    )

try:
    from scripts.export_schemas import schema_models
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from export_schemas import schema_models  # type: ignore[import-not-found, no-redef]

EXPECTED_PROVISIONS_SHA256 = (
    "523bb8fe135835dd3f0da65e49ac0f9fc367e6c6c295c39cc23ce2afc875834a"
)
EXPECTED_QUESTIONS_SHA256 = (
    "75926754fdbdd0baf0bebfd9f1dab1c6365c34b2af18aa15cb2107f3408026e9"
)
EXPECTED_SOURCE_LAW_SHA256 = (
    "4c19bcb99e7d65a87606e6f0886c5eacc1dd9d91948e01e001d74cb0083646db"
)
EXPECTED_WARNINGS_SHA256 = (
    "02f1bbcad6935e364f1dd394e59e18b1e5cbdddd7eda991d2bae850b5f4692dd"
)
EXPECTED_ENVIRONMENT_VARIABLES = (
    "POSTGRES_EXTERNAL_HOST",
    "POSTGRES_INTERNAL_HOST",
    "POSTGRES_PORT",
    "POSTGRES_ADMIN_USER",
    "POSTGRES_ADMIN_PASSWORD",
    "POSTGRES_ADMIN_DATABASE",
    "POSTGRES_LITELLM_USER",
    "POSTGRES_LITELLM_PASSWORD",
    "POSTGRES_LITELLM_DATABASE",
    "QDRANT_PUBLIC_URL",
    "QDRANT_INTERNAL_HTTP_URL",
    "QDRANT_INTERNAL_GRPC_ENDPOINT",
    "QDRANT_API_KEY",
    "LITELLM_PUBLIC_URL",
    "LITELLM_INTERNAL_URL",
    "LITELLM_API_KEY",
)
EXPECTED_RUNTIME_ENVIRONMENT_VARIABLES = (
    "POSTGRES_EXTERNAL_HOST",
    "POSTGRES_INTERNAL_HOST",
    "POSTGRES_PORT",
    "POSTGRES_LITELLM_USER",
    "POSTGRES_LITELLM_PASSWORD",
    "POSTGRES_LITELLM_DATABASE",
    "QDRANT_PUBLIC_URL",
    "QDRANT_INTERNAL_HTTP_URL",
    "QDRANT_INTERNAL_GRPC_ENDPOINT",
    "QDRANT_API_KEY",
    "LITELLM_PUBLIC_URL",
    "LITELLM_INTERNAL_URL",
    "LITELLM_API_KEY",
)
EXPECTED_POSTGRES_MIGRATION_ENVIRONMENT_VARIABLES = (
    "POSTGRES_EXTERNAL_HOST",
    "POSTGRES_INTERNAL_HOST",
    "POSTGRES_PORT",
    "POSTGRES_ADMIN_USER",
    "POSTGRES_ADMIN_PASSWORD",
    "POSTGRES_ADMIN_DATABASE",
    "POSTGRES_LITELLM_USER",
    "POSTGRES_LITELLM_DATABASE",
)
_SCAN_DIRECTORIES = (
    "src",
    "tests",
    "scripts",
    "migrations",
    "profiles",
    "schemas",
    "evaluation",
    "config",
    "deploy",
    "docs",
)
_ROOT_POLICY_FILES = (
    "AGENTS.md",
    "README.md",
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "Dockerfile",
    "compose.yaml",
    "pyproject.toml",
    "uv.lock",
)
_TEXT_SUFFIXES = frozenset(
    {".cfg", ".ini", ".json", ".md", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml"}
)
_CREDENTIAL_FLAGS = frozenset(
    {"--api-key", "--master-key", "--password", "--secret-file", "--token"}
)
_SAFE_LITERAL_MARKERS = (
    "<optional>",
    "<required>",
    "<placeholder>",
    "${",
    "fake",
    "dummy",
    "sentinel",
    "not-a-real",
    "not_real",
    "secretstr",
)


@dataclass(frozen=True, order=True, slots=True)
class Finding:
    rule: str
    path: str
    line: int = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_matches(path: Path, expected: str) -> bool:
    try:
        return _sha256(path) == expected
    except OSError:
        return False


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _policy_files(root: Path) -> tuple[list[Path], list[Finding]]:
    files: list[Path] = []
    findings: list[Finding] = []
    for relative in _ROOT_POLICY_FILES:
        path = root / relative
        if path.is_file():
            files.append(path)
    for relative in _SCAN_DIRECTORIES:
        base = root / relative
        if not base.exists():
            continue
        if _is_link_or_reparse(base):
            findings.append(Finding("filesystem_link", relative))
            continue
        for directory, names, filenames in os.walk(base, followlinks=False):
            current = Path(directory)
            retained: list[str] = []
            for name in names:
                child = current / name
                if _is_link_or_reparse(child):
                    findings.append(Finding("filesystem_link", _relative(child, root)))
                else:
                    retained.append(name)
            names[:] = retained
            for name in filenames:
                path = current / name
                if _is_link_or_reparse(path):
                    findings.append(Finding("filesystem_link", _relative(path, root)))
                elif path.suffix.casefold() in _TEXT_SUFFIXES:
                    files.append(path)
    return sorted(set(files)), findings


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _scan_runtime_independence(root: Path, files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    runtime_prefixes = ("src/", "tests/", "scripts/", "migrations/", "deploy/")
    runtime_root_files = {
        ".dockerignore",
        "Dockerfile",
        "compose.yaml",
        "pyproject.toml",
        "uv.lock",
    }
    legacy_forward = "/".join(("sample", "legal-qa"))
    legacy_backward = "\\".join(("sample", "legal-qa"))
    patterns = (
        re.compile(re.escape(legacy_forward), re.IGNORECASE),
        re.compile(re.escape(legacy_backward), re.IGNORECASE),
        re.compile(r"(?i)[A-Z]:[\\/].*?[\\/]sample[\\/]legal-qa(?:[\\/]|$)"),
        re.compile(r"(?:\.\.[\\/]){1,}.*legal[-_]qa", re.IGNORECASE),
    )
    for path in files:
        relative = _relative(path, root)
        if (
            not relative.startswith(runtime_prefixes)
            and relative not in runtime_root_files
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            findings.append(Finding("unreadable_policy_file", relative))
            continue
        for pattern in patterns:
            for match in pattern.finditer(text):
                findings.append(
                    Finding(
                        "legacy_runtime_dependency",
                        relative,
                        _line_number(text, match.start()),
                    )
                )
    return findings


def _scan_retired_technology(root: Path, files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    retired_imports = {
        "".join(("lang", "graph")),
        "".join(("oll", "ama")),
        "".join(("re", "dis")),
    }
    own_file = "scripts/verify_repository.py"
    runtime_prefixes = (
        "src/",
        "tests/",
        "scripts/",
        "migrations/",
        "profiles/",
        "deploy/",
    )
    runtime_root_files = {
        "Dockerfile",
        "compose.yaml",
        "pyproject.toml",
        "uv.lock",
    }
    text_patterns = (
        re.compile("".join(("embedding", "gemma")), re.IGNORECASE),
        re.compile("".join(("gemma", r"[ _-]?4")), re.IGNORECASE),
        re.compile(
            r"CREATE\s+EXTENSION(?:\s+IF\s+NOT\s+EXISTS)?\s+vector\b", re.IGNORECASE
        ),
        re.compile(r"\bvector\s*\(\s*\d+\s*\)", re.IGNORECASE),
        re.compile(r"\.npy\b", re.IGNORECASE),
        re.compile(r"\bREDIS_[A-Z0-9_]+\b"),
        re.compile(r"\b11434\b"),
    )
    for path in files:
        relative = _relative(path, root)
        if relative == own_file or (
            not relative.startswith(runtime_prefixes)
            and relative not in runtime_root_files
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if path.suffix == ".py":
            try:
                tree = ast.parse(text, filename=relative)
            except SyntaxError:
                findings.append(Finding("python_syntax", relative))
                continue
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                for module in modules:
                    if module.split(".", maxsplit=1)[0].casefold() in retired_imports:
                        findings.append(
                            Finding(
                                "retired_runtime_import",
                                relative,
                                int(getattr(node, "lineno", 0)),
                            )
                        )
        for pattern in text_patterns:
            for match in pattern.finditer(text):
                findings.append(
                    Finding(
                        "retired_runtime_technology",
                        relative,
                        _line_number(text, match.start()),
                    )
                )
    return findings


def _scan_credential_flags(root: Path, files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        relative = _relative(path, root)
        if not relative.startswith("scripts/") or path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for argument in node.args:
                if (
                    isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    and argument.value.casefold() in _CREDENTIAL_FLAGS
                ):
                    findings.append(
                        Finding("credential_cli_flag", relative, argument.lineno)
                    )
    return findings


def _scan_direct_environment_access(root: Path, files: list[Path]) -> list[Finding]:
    """Reject environment enumeration outside the declarative settings module."""

    findings: list[Finding] = []
    settings_file = "src/legal_qa_platform/config/settings.py"
    own_file = "scripts/verify_repository.py"
    patterns = (
        re.compile(re.escape(".".join(("os", "environ")))),
        re.compile(re.escape(".".join(("os", "getenv"))) + r"\s*\("),
        re.compile("".join(("Get-ChildItem", r"\s+Env:")), re.IGNORECASE),
        re.compile(r"(?m)^\s*printenv(?:\s|$)"),
    )
    for path in files:
        relative = _relative(path, root)
        if relative in {settings_file, own_file} or not relative.startswith(
            ("src/", "scripts/", "tests/")
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in patterns:
            for match in pattern.finditer(text):
                findings.append(
                    Finding(
                        "direct_environment_access",
                        relative,
                        _line_number(text, match.start()),
                    )
                )
    return findings


def _safe_fixture_literal(relative: str, line: str, value: str) -> bool:
    lowered = f"{line} {value}".casefold()
    if not value.strip():
        return True
    if any(marker in lowered for marker in _SAFE_LITERAL_MARKERS):
        return True
    if re.fullmatch(r"<[A-Z0-9_ -]+>", value.strip()):
        return True
    return relative.startswith("tests/") and (
        ".invalid" in lowered or "test" in lowered
    )


def _scan_secret_material(root: Path, files: list[Path]) -> list[Finding]:
    """Find high-risk literal forms without retaining or printing their values."""

    findings: list[Finding] = []
    pem_pattern = re.compile(
        "".join((r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE ", r"KEY-----")),
        re.IGNORECASE,
    )
    bearer_pattern = re.compile(
        "".join((r"\bBearer\s+", r"([A-Za-z0-9._~+/=-]{12,})")),
        re.IGNORECASE,
    )
    credential_url_pattern = re.compile(
        r"https?://([^/\s:@]+):([^@\s/]+)@",
        re.IGNORECASE,
    )
    assignment_patterns = (
        re.compile(
            r"(?i)\b(?:api[_-]?key|password|master[_-]?key|private[_-]?key|"
            r"secret|token)\s*=\s*(?:[rubf]{0,2})?[\"']([^\"']+)[\"']"
        ),
        re.compile(
            r"(?i)^\s*(?:api[_-]?key|password|master[_-]?key|private[_-]?key|"
            r"secret|token)\s*:\s*[\"']?([^\"'#\s][^#]*)"
        ),
        re.compile(
            r"^\s*[A-Z0-9_-]*(?:API_KEY|PASSWORD|MASTER_KEY|PRIVATE_KEY|SECRET|"
            r"TOKEN)\s*[=:]\s*[\"']?([^\"'#\s][^#]*)"
        ),
        re.compile(r"(?i)\bSecretStr\s*\(\s*[\"']([^\"']+)[\"']\s*\)"),
    )
    for path in files:
        relative = _relative(path, root)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            pem = pem_pattern.search(line)
            if pem and not _safe_fixture_literal(relative, line, pem.group(0)):
                findings.append(Finding("private_key_material", relative, line_number))
            bearer = bearer_pattern.search(line)
            if bearer and not _safe_fixture_literal(relative, line, bearer.group(1)):
                findings.append(Finding("bearer_literal", relative, line_number))
            credential_url = credential_url_pattern.search(line)
            if credential_url and not _safe_fixture_literal(
                relative, line, credential_url.group(0)
            ):
                findings.append(
                    Finding("credential_bearing_url", relative, line_number)
                )
            for assignment_pattern in assignment_patterns:
                assignment = assignment_pattern.search(line)
                if assignment and not _safe_fixture_literal(
                    relative, line, assignment.group(1).strip().rstrip(",")
                ):
                    findings.append(
                        Finding("credential_literal_assignment", relative, line_number)
                    )
                    break
    return findings


def _verify_environment_contract(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    if tuple(DOCUMENTED_ENVIRONMENT_VARIABLES) != EXPECTED_ENVIRONMENT_VARIABLES:
        findings.append(
            Finding(
                "environment_contract_changed",
                "src/legal_qa_platform/config/settings.py",
            )
        )

    runtime_aliases = tuple(
        str(field.validation_alias) for field in RuntimeSettings.model_fields.values()
    )
    if (
        tuple(RUNTIME_ENVIRONMENT_VARIABLES) != EXPECTED_RUNTIME_ENVIRONMENT_VARIABLES
        or runtime_aliases != EXPECTED_RUNTIME_ENVIRONMENT_VARIABLES
    ):
        findings.append(
            Finding(
                "runtime_settings_environment_alias_contract",
                "src/legal_qa_platform/config/settings.py",
            )
        )
    migration_aliases = tuple(
        str(field.validation_alias)
        for field in PostgresMigrationSettings.model_fields.values()
    )
    if (
        tuple(POSTGRES_MIGRATION_ENVIRONMENT_VARIABLES)
        != EXPECTED_POSTGRES_MIGRATION_ENVIRONMENT_VARIABLES
        or migration_aliases != EXPECTED_POSTGRES_MIGRATION_ENVIRONMENT_VARIABLES
    ):
        findings.append(
            Finding(
                "migration_settings_environment_alias_contract",
                "src/legal_qa_platform/config/settings.py",
            )
        )
    for settings_type, field_name in (
        (PostgresMigrationSettings, "postgres_admin_password"),
        (RuntimeSettings, "postgres_password"),
        (RuntimeSettings, "qdrant_api_key"),
        (RuntimeSettings, "litellm_api_key"),
    ):
        annotation = settings_type.model_fields[field_name].annotation
        if annotation is not SecretStr and SecretStr not in get_args(annotation):
            findings.append(
                Finding(
                    "sensitive_setting_not_redacted",
                    "src/legal_qa_platform/config/settings.py",
                )
            )
    for settings_type in (RuntimeSettings, PostgresMigrationSettings):
        if settings_type.model_config.get("env_file") is not None:
            findings.append(
                Finding(
                    "dotenv_loading_not_disabled",
                    "src/legal_qa_platform/config/settings.py",
                )
            )

    example = root / ".env.example"
    try:
        lines = example.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [Finding("missing_environment_example", ".env.example")]
    seen: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        seen.append(key)
        if not separator or key not in EXPECTED_ENVIRONMENT_VARIABLES:
            findings.append(
                Finding("undocumented_environment_name", ".env.example", line_number)
            )
        if value and not re.fullmatch(r"<[A-Z_]+>", value):
            findings.append(
                Finding(
                    "non_placeholder_environment_value", ".env.example", line_number
                )
            )
    if tuple(seen) != EXPECTED_ENVIRONMENT_VARIABLES:
        findings.append(Finding("environment_example_contract", ".env.example"))

    settings_path = root / "src" / "legal_qa_platform" / "config" / "settings.py"
    try:
        settings_text = settings_path.read_text(encoding="utf-8")
    except OSError:
        return findings + [
            Finding("missing_settings_contract", _relative(settings_path, root))
        ]
    if not re.search(r"env_file\s*=\s*None\b", settings_text):
        findings.append(
            Finding("dotenv_loading_not_disabled", _relative(settings_path, root))
        )
    if re.search(r"(?i)(?:from|import)\s+(?:python_)?dotenv\b", settings_text):
        findings.append(Finding("dotenv_import", _relative(settings_path, root)))
    return findings


def _verify_deployment_secret_references(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    deployment_path = root / "deploy" / "kubernetes" / "api-deployment.yaml"
    kubernetes_dir = root / "deploy" / "kubernetes"
    try:
        deployment = deployment_path.read_text(encoding="utf-8")
    except OSError:
        return [
            Finding(
                "missing_kubernetes_api_deployment", _relative(deployment_path, root)
            )
        ]
    for name in (
        "POSTGRES_LITELLM_USER",
        "POSTGRES_LITELLM_PASSWORD",
        "POSTGRES_LITELLM_DATABASE",
        "QDRANT_API_KEY",
        "LITELLM_API_KEY",
    ):
        block = re.search(
            rf"- name:\s*{re.escape(name)}\s+valueFrom:\s+secretKeyRef:",
            deployment,
        )
        if block is None:
            findings.append(
                Finding(
                    "missing_secret_key_reference", _relative(deployment_path, root)
                )
            )
    for path in kubernetes_dir.glob("*.yaml") if kubernetes_dir.exists() else ():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            findings.append(Finding("unreadable_policy_file", _relative(path, root)))
            continue
        if re.search(r"(?m)^kind:\s*Secret\s*$", text) or re.search(
            r"(?m)^stringData:\s*$", text
        ):
            findings.append(
                Finding("kubernetes_secret_material", _relative(path, root))
            )
    return findings


def _verify_required_files(root: Path) -> list[Finding]:
    required = (
        "data/legal_provisions.json",
        "data/qa_test_questions.json",
        "data/source_law.txt",
        "data/collection_warnings.json",
        "migrations/0001_initial.sql",
        "profiles/platform-baseline-v1.json",
        "scripts/migrate.py",
        "scripts/sync_laws.py",
        "scripts/smoke_test.py",
        "scripts/evaluate.py",
        "scripts/load_test.py",
        "scripts/export_schemas.py",
        "scripts/verify_repository.py",
        "evaluation/baselines/platform-baseline-v1.json",
        "schemas/chat_request.schema.json",
        "schemas/chat_response.schema.json",
        "schemas/context_item.schema.json",
        "schemas/error_response.schema.json",
        "schemas/feedback_request.schema.json",
        "schemas/feedback_response.schema.json",
        "schemas/health_response.schema.json",
        "schemas/legal_provision.schema.json",
        "schemas/legal_qa_response.schema.json",
        "schemas/llm_answer.schema.json",
        "schemas/question_bank_item.schema.json",
        "schemas/rag_context.schema.json",
        "schemas/rag_profile.schema.json",
        "schemas/readiness_response.schema.json",
        "schemas/retrieval_result.schema.json",
        "schemas/retrieve_request.schema.json",
        "schemas/retrieve_response.schema.json",
    )
    return [
        Finding("required_file_missing", relative)
        for relative in required
        if not (root / relative).is_file()
    ]


def _verify_data(root: Path) -> tuple[list[Finding], dict[str, int]]:
    provisions_path = root / "data" / "legal_provisions.json"
    questions_path = root / "data" / "qa_test_questions.json"
    findings: list[Finding] = []
    stats = {"provisions": 0, "documents": 0, "questions": 0}
    try:
        bundle = load_data_bundle(provisions_path, questions_path)
    except Exception:
        return [Finding("data_contract", "data")], stats
    stats = {
        "provisions": len(bundle.provisions),
        "documents": len({item.document_name for item in bundle.provisions}),
        "questions": len(bundle.questions),
    }
    if stats != {"provisions": 2_234, "documents": 223, "questions": 100}:
        findings.append(Finding("baseline_data_counts", "data"))
    provision_ids = [item.provision_id for item in bundle.provisions]
    if provision_ids != list(range(9, 2_243)):
        findings.append(
            Finding("stable_provision_id_range", "data/legal_provisions.json")
        )
    question_ids = [item.question_id for item in bundle.questions]
    if question_ids != [f"Q{index:03d}" for index in range(1, 101)]:
        findings.append(Finding("question_id_sequence", "data/qa_test_questions.json"))
    if not _hash_matches(provisions_path, EXPECTED_PROVISIONS_SHA256):
        findings.append(Finding("provision_dataset_hash", "data/legal_provisions.json"))
    if not _hash_matches(questions_path, EXPECTED_QUESTIONS_SHA256):
        findings.append(Finding("question_dataset_hash", "data/qa_test_questions.json"))
    if not _hash_matches(root / "data" / "source_law.txt", EXPECTED_SOURCE_LAW_SHA256):
        findings.append(Finding("source_law_hash", "data/source_law.txt"))
    if not _hash_matches(
        root / "data" / "collection_warnings.json", EXPECTED_WARNINGS_SHA256
    ):
        findings.append(
            Finding("collection_warnings_hash", "data/collection_warnings.json")
        )

    try:
        profile = load_profile(root / "profiles" / "platform-baseline-v1.json")
    except Exception:
        findings.append(
            Finding("profile_contract", "profiles/platform-baseline-v1.json")
        )
    else:
        if (
            profile.embedding_model != "bge-m3"
            or profile.embedding_dimension != 1_024
            or profile.chat_model != "campus-qa"
            or profile.reranker_enabled
            or profile.top_k != 6
        ):
            findings.append(
                Finding(
                    "baseline_profile_contract", "profiles/platform-baseline-v1.json"
                )
            )
    migration = root / "migrations" / "0001_initial.sql"
    try:
        migration_text = migration.read_text(encoding="utf-8")
    except OSError:
        findings.append(Finding("migration_contract", "migrations/0001_initial.sql"))
    else:
        if not re.search(
            r"generate_series\s*\(\s*1\s*,\s*8\s*\)", migration_text, re.IGNORECASE
        ):
            findings.append(
                Finding("legacy_id_reservation", "migrations/0001_initial.sql")
            )
    return findings, stats


def _verify_evaluation_baseline(root: Path) -> list[Finding]:
    relative = "evaluation/baselines/platform-baseline-v1.json"
    path = root / relative
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [Finding("evaluation_baseline_contract", relative)]
    dataset = payload.get("dataset") if isinstance(payload, dict) else None
    profile = payload.get("profile") if isinstance(payload, dict) else None
    try:
        expected_profile_hash = _sha256(root / "profiles" / "platform-baseline-v1.json")
    except OSError:
        return [Finding("evaluation_baseline_contract", relative)]
    valid = bool(
        payload.get("baseline_id") == "platform-baseline-v1"
        and payload.get("application_version") == __version__
        and payload.get("status") in {"unrun", "completed"}
        and isinstance(dataset, dict)
        and dataset.get("question_count") == 100
        and dataset.get("provision_count") == 2_234
        and dataset.get("questions_sha256") == EXPECTED_QUESTIONS_SHA256
        and dataset.get("provisions_sha256") == EXPECTED_PROVISIONS_SHA256
        and dataset.get("source_law_sha256") == EXPECTED_SOURCE_LAW_SHA256
        and dataset.get("collection_warnings_sha256") == EXPECTED_WARNINGS_SHA256
        and isinstance(profile, dict)
        and profile.get("profile_sha256") == expected_profile_hash
        and profile.get("reranker_enabled") is False
    )
    return [] if valid else [Finding("evaluation_baseline_contract", relative)]


def _verify_schema_exports(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for name, model in schema_models().items():
        relative = f"schemas/{name}.schema.json"
        try:
            actual = json.loads((root / relative).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            findings.append(Finding("schema_export_contract", relative))
            continue
        if actual != model.model_json_schema(mode="validation"):
            findings.append(Finding("schema_export_contract", relative))
    return findings


def run_verification(root: Path = PROJECT_ROOT) -> tuple[list[Finding], dict[str, int]]:
    """Run all offline checks without reading outside ``root``."""

    resolved = root.resolve()
    files, link_findings = _policy_files(resolved)
    findings = [
        *link_findings,
        *_verify_required_files(resolved),
        *_scan_runtime_independence(resolved, files),
        *_scan_retired_technology(resolved, files),
        *_scan_credential_flags(resolved, files),
        *_scan_direct_environment_access(resolved, files),
        *_scan_secret_material(resolved, files),
        *_verify_environment_contract(resolved),
        *_verify_deployment_secret_references(resolved),
        *_verify_evaluation_baseline(resolved),
        *_verify_schema_exports(resolved),
    ]
    data_findings, stats = _verify_data(resolved)
    findings.extend(data_findings)
    return sorted(set(findings)), stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify repository independence and security contracts."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root; must resolve inside legal_qa_platform.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = repository_path(args.root, default=PROJECT_ROOT)
    except ValueError:
        print("[FAIL] repository root must stay inside legal_qa_platform.")
        return 2
    findings, stats = run_verification(root)
    if findings:
        for finding in findings:
            line = f":{finding.line}" if finding.line else ""
            print(f"[FAIL] rule={finding.rule} file={finding.path}{line}")
        print(f"[FAIL] repository verification findings={len(findings)}")
        return 1
    print(
        "[PASS] repository verification "
        f"provisions={stats['provisions']} documents={stats['documents']} "
        f"questions={stats['questions']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
