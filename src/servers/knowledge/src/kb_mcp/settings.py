"""Knowledge Base MCP Server configuration."""

from pydantic import Field, HttpUrl, PositiveInt, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from kb_mcp.contracts.constants import DEFAULT_EMBEDDING_MODEL
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
    database_url: SecretStr | None = Field(
        default=None,
        description="Async PostgreSQL connection URL (KNOWLEDGE_DATABASE_URL)",
    )
    pool_pre_ping: bool = Field(
        default=True,
        description="Enable connection health checks before checkout from pool",
    )
    pool_size: PositiveInt = Field(
        default=5,
        description="Connection pool size for knowledge postgres engine",
    )
    max_overflow: int = Field(
        default=10,
        description="Max overflow connections beyond pool size",
    )
    pool_recycle_seconds: int = Field(
        default=1800,
        description="Recycle connections after specified seconds",
    )
    max_search_results_ceiling: int = Field(
        default=50,
        ge=1,
        le=50,
        description="Hard ceiling for knowledge search results",
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
        description="Database or API request timeout in seconds",
    )
    max_search_results: PositiveInt = Field(
        default=5,
        ge=1,
        le=50,
        description="Default top-K documentation chunks returned per query",
    )

    embedding_model: str = Field(
        default=DEFAULT_EMBEDDING_MODEL,
        description="Approved local embedding model identifier",
    )
    embedding_cache_dir: str | None = Field(
        default=None,
        description="Optional custom directory for FastEmbed cached model artifacts",
    )

    @field_validator("embedding_model")
    @classmethod
    def validate_embedding_model(cls, v: str) -> str:
        if v != DEFAULT_EMBEDDING_MODEL:
            raise ValueError(
                f"Embedding model '{v}' is not supported. "
                f"Only approved model '{DEFAULT_EMBEDDING_MODEL}' is allowed."
            )
        return v

    @property
    def is_database_configured(self) -> bool:
        """Return True if database_url is configured with a non-empty string."""
        return bool(self.database_url and self.database_url.get_secret_value().strip())

    def get_async_database_url(self) -> str:
        """Return normalized postgresql+asyncpg database URL or raise error."""
        if not self.is_database_configured or self.database_url is None:
            raise ValueError("Knowledge database URL is not configured.")
        raw_url = self.database_url.get_secret_value().strip()
        if raw_url.startswith("postgresql://"):
            return raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if raw_url.startswith("postgres://"):
            return raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
        if raw_url.startswith("postgresql+asyncpg://"):
            return raw_url
        raise ValueError(
            "Unsupported database scheme in URL. Must start with 'postgresql://', "
            "'postgres://', or 'postgresql+asyncpg://'."
        )

    security: SecuritySettings = SecuritySettings()
    logging: LoggingSettings = LoggingSettings()
