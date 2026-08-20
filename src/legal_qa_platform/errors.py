"""Public, secret-safe error taxonomy used across application boundaries."""

from __future__ import annotations


class LegalQaError(RuntimeError):
    """Base class for errors safe to classify at the application boundary."""


class ConfigurationError(LegalQaError):
    """Runtime configuration is incomplete or internally inconsistent."""


class DataContractError(LegalQaError):
    """Checked-in or incoming legal data violates a declared contract."""


class ExternalServiceError(LegalQaError):
    """An external dependency failed without exposing its credentials."""

    def __init__(self, service: str, category: str, detail: str = "") -> None:
        self.service = service
        self.category = category
        self.detail = detail
        message = f"{service} failure: {category}"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)


class ResponseValidationError(LegalQaError):
    """A model response could not be converted to an allowed response."""


class IdentityConflictError(DataContractError):
    """A stable provision ID or stable key would be reassigned."""
