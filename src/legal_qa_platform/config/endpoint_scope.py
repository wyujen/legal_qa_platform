"""Pure endpoint-family selection for operator and runtime commands.

The selector only clears fields on an immutable settings copy.  It never reads
or mutates the process environment and never returns endpoint values in status
metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast, overload

from .settings import PostgresMigrationSettings, RuntimeSettings

EndpointScope = Literal["auto", "public", "internal"]
EndpointFamily = Literal["external", "public", "internal", "missing"]

ENDPOINT_SCOPE_CHOICES: tuple[EndpointScope, ...] = (
    "auto",
    "public",
    "internal",
)


@dataclass(frozen=True, slots=True)
class RuntimeEndpointFamilies:
    """Allowlisted endpoint-family metadata safe for diagnostics."""

    postgres: EndpointFamily
    qdrant: EndpointFamily
    litellm: EndpointFamily


@overload
def select_endpoint_scope(
    settings: RuntimeSettings,
    scope: EndpointScope,
) -> RuntimeSettings: ...


@overload
def select_endpoint_scope(
    settings: PostgresMigrationSettings,
    scope: EndpointScope,
) -> PostgresMigrationSettings: ...


def select_endpoint_scope(
    settings: RuntimeSettings | PostgresMigrationSettings,
    scope: EndpointScope,
) -> RuntimeSettings | PostgresMigrationSettings:
    """Select documented endpoint fields without mutating environment state."""

    if scope not in ENDPOINT_SCOPE_CHOICES:
        raise ValueError("Unsupported endpoint scope.")
    if scope == "auto":
        return settings

    if isinstance(settings, RuntimeSettings):
        if scope == "public":
            return settings.model_copy(
                update={
                    "postgres_internal_host": None,
                    "qdrant_internal_http_url": None,
                    "qdrant_internal_grpc_endpoint": None,
                    "litellm_internal_url": None,
                }
            )
        return settings.model_copy(
            update={
                "postgres_external_host": None,
                "qdrant_public_url": None,
                "litellm_public_url": None,
            }
        )

    if scope == "public":
        return settings.model_copy(update={"postgres_internal_host": None})
    return settings.model_copy(update={"postgres_external_host": None})


def runtime_endpoint_families(settings: RuntimeSettings) -> RuntimeEndpointFamilies:
    """Describe selected families without retaining or exposing their values."""

    status = settings.safe_status()
    return RuntimeEndpointFamilies(
        postgres=_endpoint_family(status["postgres_endpoint"]),
        qdrant=_endpoint_family(status["qdrant_endpoint"]),
        litellm=_endpoint_family(status["litellm_endpoint"]),
    )


def postgres_endpoint_family(
    settings: RuntimeSettings | PostgresMigrationSettings,
) -> EndpointFamily:
    """Return only the selected PostgreSQL family label."""

    if settings.postgres_internal_host:
        return "internal"
    if settings.postgres_external_host:
        return "external"
    return "missing"


def missing_for_runtime_scope(
    settings: RuntimeSettings,
    scope: EndpointScope,
) -> tuple[str, ...]:
    """Return precise variable names for explicitly selected endpoint families."""

    return _scope_missing_names(settings.missing_for_runtime(), scope)


def missing_for_migration_scope(
    settings: PostgresMigrationSettings,
    scope: EndpointScope,
) -> tuple[str, ...]:
    """Return precise PostgreSQL names for an explicit migration scope."""

    return _scope_missing_names(settings.missing_for_migration(), scope)


def _scope_missing_names(
    missing: tuple[str, ...],
    scope: EndpointScope,
) -> tuple[str, ...]:
    if scope == "auto":
        return missing
    replacements = {
        "POSTGRES_INTERNAL_HOST or POSTGRES_EXTERNAL_HOST": (
            "POSTGRES_EXTERNAL_HOST" if scope == "public" else "POSTGRES_INTERNAL_HOST"
        ),
        "QDRANT_INTERNAL_HTTP_URL or QDRANT_PUBLIC_URL": (
            "QDRANT_PUBLIC_URL" if scope == "public" else "QDRANT_INTERNAL_HTTP_URL"
        ),
        "LITELLM_INTERNAL_URL or LITELLM_PUBLIC_URL": (
            "LITELLM_PUBLIC_URL" if scope == "public" else "LITELLM_INTERNAL_URL"
        ),
    }
    return tuple(replacements.get(name, name) for name in missing)


def _endpoint_family(value: str | bool) -> EndpointFamily:
    if value in {"external", "public", "internal", "missing"}:
        return cast(EndpointFamily, value)
    raise ValueError("Unexpected endpoint-family status.")


__all__ = [
    "ENDPOINT_SCOPE_CHOICES",
    "EndpointScope",
    "RuntimeEndpointFamilies",
    "missing_for_migration_scope",
    "missing_for_runtime_scope",
    "postgres_endpoint_family",
    "runtime_endpoint_families",
    "select_endpoint_scope",
]
