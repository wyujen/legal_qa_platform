"""Application and operator configuration from the process environment only."""

from .settings import PostgresMigrationSettings, RuntimeSettings

__all__ = ["PostgresMigrationSettings", "RuntimeSettings"]
