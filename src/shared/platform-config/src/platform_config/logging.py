"""Logging and telemetry typed configuration."""

from enum import StrEnum

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from platform_config.base import BasePlatformSettings


class LogLevel(StrEnum):
    """Supported logging severity levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(StrEnum):
    """Supported structured log output formats."""

    JSON = "JSON"
    CONSOLE = "CONSOLE"


class LoggingSettings(BasePlatformSettings):
    """Configuration for structured logging across all platform components."""

    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        env_file=".env",
        extra="ignore",
    )

    level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Minimum log severity level",
    )
    format: LogFormat = Field(
        default=LogFormat.JSON,
        description="Log output format (JSON for production, CONSOLE for local)",
    )
    include_caller_info: bool = Field(
        default=True,
        description="Attach file, line number, and function name to log events",
    )
