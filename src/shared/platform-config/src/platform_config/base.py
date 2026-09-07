"""Base Pydantic settings abstractions for the platform."""

from enum import StrEnum

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvironmentType(StrEnum):
    """Execution environment tiers."""

    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class BasePlatformSettings(BaseSettings):
    """Abstract base settings with fail-fast validation and standard configuration rules."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        validate_default=True,
    )

    environment: EnvironmentType = Field(
        default=EnvironmentType.LOCAL,
        description="Active runtime environment tier",
    )
    app_name: str = Field(
        default="superoffice-ai-platform",
        description="Application identifier for telemetry and logging",
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode (forbidden in production)",
    )

    @model_validator(mode="after")
    def validate_environment_constraints(self) -> "BasePlatformSettings":
        """Enforce environment-specific safety invariants."""
        if self.environment == EnvironmentType.PRODUCTION and self.debug:
            msg = "Debug mode cannot be enabled in production environments."
            raise ValueError(msg)
        return self
