"""Knowledge Base MCP Server configuration."""

from pydantic import Field, HttpUrl, PositiveInt, SecretStr
from pydantic_settings import SettingsConfigDict

from platform_config.base import BasePlatformSettings
from platform_config.logging import LoggingSettings
from platform_config.security import SecuritySettings


class KnowledgeServerSettings(BasePlatformSettings):
    """Configuration for the Knowledge Base & Runbook MCP Server."""

    model_config = SettingsConfigDict(
        env_prefix="KNOWLEDGE_",
        env_file=".env",
        extra="ignore",
    )

    port: PositiveInt = Field(
        default=8003,
        description="Internal Streamable HTTP listener port",
    )
    supabase_url: HttpUrl = Field(
        default=HttpUrl("https://placeholder.supabase.co"),
        description="Supabase service instance URL",
    )
    supabase_anon_key: SecretStr = Field(
        default=SecretStr("insecure-dev-placeholder"),
        description="Supabase anonymous service API key",
    )
    match_documents_rpc: str | None = Field(
        default=None,
        description="Verified PostgREST RPC function name for vector similarity search",
    )
    runbooks_table: str | None = Field(
        default=None,
        description="Verified PostgREST table or view name for operational runbooks",
    )
    known_issues_table: str | None = Field(
        default=None,
        description="Verified PostgREST table or view name for known issues and workarounds",
    )
    timeout_seconds: PositiveInt = Field(
        default=10,
        description="Supabase API request timeout in seconds",
    )
    max_search_results: PositiveInt = Field(
        default=5,
        ge=1,
        le=50,
        description="Default top-K documentation chunks returned per query",
    )

    security: SecuritySettings = SecuritySettings()
    logging: LoggingSettings = LoggingSettings()
