"""Investigation MCP Server configuration."""

from pydantic import Field, HttpUrl, PositiveInt
from pydantic_settings import SettingsConfigDict

from platform_config.base import BasePlatformSettings
from platform_config.logging import LoggingSettings
from platform_config.security import SecuritySettings


class InvestigationServerSettings(BasePlatformSettings):
    """Configuration for the Investigation Orchestration MCP Server."""

    model_config = SettingsConfigDict(
        env_prefix="INVESTIGATION_",
        env_file=".env",
        extra="ignore",
    )

    host: str = Field(
        default="0.0.0.0",
        description="Internal Streamable HTTP listener bind host",
    )
    port: PositiveInt = Field(
        default=8005,
        description="Internal Streamable HTTP listener port (default 8005)",
    )
    superoffice_mcp_url: HttpUrl = Field(
        default=HttpUrl("http://127.0.0.1:8001"),
        description="Endpoint URL for downstream SuperOffice MCP server",
    )
    diagnostics_mcp_url: HttpUrl = Field(
        default=HttpUrl("http://127.0.0.1:8002"),
        description="Endpoint URL for downstream Diagnostics MCP server",
    )
    knowledge_mcp_url: HttpUrl | None = Field(
        default=None,
        description="Endpoint URL for downstream Knowledge Base MCP server (optional)",
    )
    timeout_seconds: PositiveInt = Field(
        default=30,
        description="HTTP request timeout for downstream MCP server calls",
    )

    security: SecuritySettings = SecuritySettings()
    logging: LoggingSettings = LoggingSettings()
