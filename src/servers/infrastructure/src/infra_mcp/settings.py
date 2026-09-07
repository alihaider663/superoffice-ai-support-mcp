"""Infrastructure MCP Server configuration."""

from pydantic import Field, PositiveInt
from pydantic_settings import SettingsConfigDict

from platform_config.base import BasePlatformSettings
from platform_config.logging import LoggingSettings
from platform_config.security import SecuritySettings


class InfrastructureServerSettings(BasePlatformSettings):
    """Configuration for the Host & Infrastructure Diagnostics MCP Server."""

    model_config = SettingsConfigDict(
        env_prefix="INFRASTRUCTURE_",
        env_file=".env",
        extra="ignore",
    )

    port: PositiveInt = Field(
        default=8004,
        description="Internal Streamable HTTP listener port",
    )
    collect_disk_metrics: bool = Field(
        default=True,
        description="Enable host disk volume capacity probes",
    )
    collect_memory_metrics: bool = Field(
        default=True,
        description="Enable host RAM and virtual memory metrics probes",
    )
    collect_iis_metrics: bool = Field(
        default=True,
        description="Enable IIS worker process and app pool health monitoring",
    )

    security: SecuritySettings = SecuritySettings()
    logging: LoggingSettings = LoggingSettings()
