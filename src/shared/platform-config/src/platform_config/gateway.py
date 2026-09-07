"""Gateway-specific typed configuration settings."""

from pydantic import Field, HttpUrl, PositiveInt
from pydantic_settings import SettingsConfigDict

from platform_config.base import BasePlatformSettings


class GatewaySettings(BasePlatformSettings):
    """Configuration for the central MCP Gateway service."""

    model_config = SettingsConfigDict(
        env_prefix="GATEWAY_",
        env_file=".env",
        extra="ignore",
    )

    host: str = Field(
        default="0.0.0.0",
        description="Bind host address for Streamable HTTP listener",
    )
    port: PositiveInt = Field(
        default=8000,
        description="Port for Streamable HTTP listener",
    )
    request_timeout_seconds: PositiveInt = Field(
        default=30,
        description="Global gateway request processing timeout",
    )
    max_concurrent_requests: PositiveInt = Field(
        default=100,
        description="Maximum concurrent Streamable HTTP streams",
    )

    # Downstream server connection endpoints (internal routing)
    superoffice_mcp_url: HttpUrl = Field(
        default=HttpUrl("http://127.0.0.1:8001"),
        description="Endpoint for downstream SuperOffice MCP server",
    )
    diagnostics_mcp_url: HttpUrl = Field(
        default=HttpUrl("http://127.0.0.1:8002"),
        description="Endpoint for downstream Diagnostics MCP server",
    )
    knowledge_mcp_url: HttpUrl = Field(
        default=HttpUrl("http://127.0.0.1:8003"),
        description="Endpoint for downstream Knowledge MCP server",
    )
    infrastructure_mcp_url: HttpUrl = Field(
        default=HttpUrl("http://127.0.0.1:8004"),
        description="Endpoint for downstream Infrastructure MCP server",
    )
    investigation_mcp_url: HttpUrl = Field(
        default=HttpUrl("http://127.0.0.1:8005"),
        description="Endpoint for downstream Investigation MCP server",
    )
