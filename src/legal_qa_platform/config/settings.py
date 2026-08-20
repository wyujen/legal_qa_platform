"""Secret-safe runtime environment contract.

This module deliberately does not load dotenv files or inspect the wider process
environment. Pydantic reads only the explicitly declared variable names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from legal_qa_platform.errors import ConfigurationError

DOCUMENTED_ENVIRONMENT_VARIABLES = (
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


@dataclass(frozen=True, slots=True)
class ResolvedEndpoints:
    """Resolved service endpoints without any credential material."""

    postgres_host: str
    postgres_port: int
    qdrant_http_url: str
    litellm_url: str


@dataclass(frozen=True, slots=True)
class ResolvedPostgresEndpoint:
    """PostgreSQL coordinates resolved independently for migration tooling."""

    host: str
    port: int


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _valid_http_endpoint(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return False
    return bool(
        parsed.scheme in {"http", "https"}
        and hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _valid_postgres_host(value: str) -> bool:
    return "://" not in value and not any(
        marker in value for marker in ("@", "/", "?", "#")
    )


class RuntimeSettings(BaseSettings):
    """The complete and intentionally small runtime configuration contract."""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        extra="ignore",
        frozen=True,
    )

    environment_names: ClassVar[tuple[str, ...]] = DOCUMENTED_ENVIRONMENT_VARIABLES

    postgres_external_host: str | None = Field(
        default=None, validation_alias="POSTGRES_EXTERNAL_HOST"
    )
    postgres_internal_host: str | None = Field(
        default=None, validation_alias="POSTGRES_INTERNAL_HOST"
    )
    postgres_port: int | None = Field(
        default=None, validation_alias="POSTGRES_PORT", ge=1, le=65535
    )
    postgres_user: str | None = Field(
        default=None, validation_alias="POSTGRES_LITELLM_USER"
    )
    postgres_password: SecretStr | None = Field(
        default=None, validation_alias="POSTGRES_LITELLM_PASSWORD"
    )
    postgres_database: str | None = Field(
        default=None, validation_alias="POSTGRES_LITELLM_DATABASE"
    )

    qdrant_public_url: str | None = Field(
        default=None, validation_alias="QDRANT_PUBLIC_URL"
    )
    qdrant_internal_http_url: str | None = Field(
        default=None, validation_alias="QDRANT_INTERNAL_HTTP_URL"
    )
    qdrant_internal_grpc_endpoint: str | None = Field(
        default=None, validation_alias="QDRANT_INTERNAL_GRPC_ENDPOINT"
    )
    qdrant_api_key: SecretStr | None = Field(
        default=None, validation_alias="QDRANT_API_KEY"
    )

    litellm_public_url: str | None = Field(
        default=None, validation_alias="LITELLM_PUBLIC_URL"
    )
    litellm_internal_url: str | None = Field(
        default=None, validation_alias="LITELLM_INTERNAL_URL"
    )
    litellm_api_key: SecretStr | None = Field(
        default=None, validation_alias="LITELLM_API_KEY"
    )

    _normalize_blanks = field_validator("*", mode="before")(_blank_to_none)

    @property
    def postgres_host(self) -> str | None:
        """Prefer the internal endpoint when both endpoint families exist."""

        return self.postgres_internal_host or self.postgres_external_host

    @property
    def qdrant_http_url(self) -> str | None:
        endpoint = self.qdrant_internal_http_url or self.qdrant_public_url
        return endpoint.rstrip("/") if endpoint else None

    @property
    def litellm_url(self) -> str | None:
        endpoint = self.litellm_internal_url or self.litellm_public_url
        return endpoint.rstrip("/") if endpoint else None

    def missing_for_postgres(self) -> tuple[str, ...]:
        """Return missing PostgreSQL variable names without any values."""

        missing: list[str] = []
        if self.postgres_host is None:
            missing.append("POSTGRES_INTERNAL_HOST or POSTGRES_EXTERNAL_HOST")
        if self.postgres_port is None:
            missing.append("POSTGRES_PORT")
        if self.postgres_user is None:
            missing.append("POSTGRES_LITELLM_USER")
        if self.postgres_password is None:
            missing.append("POSTGRES_LITELLM_PASSWORD")
        if self.postgres_database is None:
            missing.append("POSTGRES_LITELLM_DATABASE")
        return tuple(missing)

    def missing_for_qdrant(self) -> tuple[str, ...]:
        """Return missing Qdrant variable names without any values."""

        missing: list[str] = []
        if self.qdrant_http_url is None:
            missing.append("QDRANT_INTERNAL_HTTP_URL or QDRANT_PUBLIC_URL")
        if self.qdrant_api_key is None:
            missing.append("QDRANT_API_KEY")
        return tuple(missing)

    def missing_for_litellm(self) -> tuple[str, ...]:
        """Return missing LiteLLM variable names without any values."""

        missing: list[str] = []
        if self.litellm_url is None:
            missing.append("LITELLM_INTERNAL_URL or LITELLM_PUBLIC_URL")
        if self.litellm_api_key is None:
            missing.append("LITELLM_API_KEY")
        return tuple(missing)

    def missing_for_runtime(self) -> tuple[str, ...]:
        """Return names only; never include values in diagnostics."""

        return (
            *self.missing_for_postgres(),
            *self.missing_for_qdrant(),
            *self.missing_for_litellm(),
        )

    @staticmethod
    def _raise_missing(missing: tuple[str, ...]) -> None:
        if missing:
            raise ConfigurationError(
                "Missing required environment variable(s): " + ", ".join(missing)
            )

    def require_postgres(self) -> ResolvedPostgresEndpoint:
        """Resolve only PostgreSQL for isolated migration/admin commands."""

        self._raise_missing(self.missing_for_postgres())
        assert self.postgres_host is not None
        assert self.postgres_port is not None
        if not _valid_postgres_host(self.postgres_host):
            raise ConfigurationError(
                "Invalid endpoint environment variable: "
                "POSTGRES_INTERNAL_HOST or POSTGRES_EXTERNAL_HOST"
            )
        return ResolvedPostgresEndpoint(
            host=self.postgres_host,
            port=self.postgres_port,
        )

    def require_runtime(self) -> ResolvedEndpoints:
        """Fail before composing live adapters, reporting variable names only."""

        missing = self.missing_for_runtime()
        self._raise_missing(missing)
        assert self.postgres_host is not None
        assert self.postgres_port is not None
        assert self.qdrant_http_url is not None
        assert self.litellm_url is not None
        invalid_endpoints: list[str] = []
        if not _valid_postgres_host(self.postgres_host):
            invalid_endpoints.append("POSTGRES_INTERNAL_HOST or POSTGRES_EXTERNAL_HOST")
        if not _valid_http_endpoint(self.qdrant_http_url):
            invalid_endpoints.append("QDRANT_INTERNAL_HTTP_URL or QDRANT_PUBLIC_URL")
        if not _valid_http_endpoint(self.litellm_url):
            invalid_endpoints.append("LITELLM_INTERNAL_URL or LITELLM_PUBLIC_URL")
        if invalid_endpoints:
            raise ConfigurationError(
                "Invalid endpoint environment variable(s): "
                + ", ".join(invalid_endpoints)
            )
        return ResolvedEndpoints(
            postgres_host=self.postgres_host,
            postgres_port=self.postgres_port,
            qdrant_http_url=self.qdrant_http_url,
            litellm_url=self.litellm_url,
        )

    def safe_status(self) -> dict[str, str | bool]:
        """Return an allowlisted status that is safe for logs and health output."""

        return {
            "postgres_endpoint": "internal"
            if self.postgres_internal_host
            else "external"
            if self.postgres_external_host
            else "missing",
            "qdrant_endpoint": "internal"
            if self.qdrant_internal_http_url
            else "public"
            if self.qdrant_public_url
            else "missing",
            "litellm_endpoint": "internal"
            if self.litellm_internal_url
            else "public"
            if self.litellm_public_url
            else "missing",
            "postgres_credentials_present": bool(
                self.postgres_user and self.postgres_password and self.postgres_database
            ),
            "qdrant_credential_present": self.qdrant_api_key is not None,
            "litellm_credential_present": self.litellm_api_key is not None,
        }
