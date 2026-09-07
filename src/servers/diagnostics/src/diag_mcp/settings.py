"""Diagnostics MCP Server configuration."""

from pathlib import Path

from pydantic import Field, PositiveInt, SecretStr
from pydantic_settings import SettingsConfigDict

from platform_config.base import BasePlatformSettings
from platform_config.logging import LoggingSettings
from platform_config.security import SecuritySettings


class DiagnosticsServerSettings(BasePlatformSettings):
    """Configuration for the Database & Log Diagnostics MCP Server."""

    model_config = SettingsConfigDict(
        env_prefix="DIAGNOSTICS_",
        env_file=".env",
        extra="ignore",
    )

    port: PositiveInt = Field(
        default=8002,
        description="Internal Streamable HTTP listener port",
    )
    mssql_host: str = Field(
        default="localhost",
        description="MSSQL database hostname or IP address",
    )
    mssql_port: PositiveInt = Field(
        default=1433,
        description="MSSQL port",
    )
    mssql_database: str = Field(
        default="SuperOffice",
        description="SuperOffice database catalog name",
    )
    mssql_user: str = Field(
        default="so_readonly_user",
        description="Read-only database service user",
    )
    mssql_password: SecretStr = Field(
        default=SecretStr("insecure-dev-placeholder"),
        description="Read-only database password",
    )
    mssql_login_timeout_seconds: PositiveInt = Field(
        default=5,
        description="Database login/connection timeout in seconds",
    )
    mssql_query_timeout_seconds: PositiveInt = Field(
        default=5,
        description="Hard statement query timeout in seconds (canonical: 5s)",
    )
    mssql_max_rows: PositiveInt = Field(
        default=50,
        description="Hard upper bound for result rows per query (canonical: 50)",
    )
    mssql_isolation_level: str = Field(
        default="SNAPSHOT",
        description="Transaction isolation level (canonical: SNAPSHOT)",
    )
    mssql_pool_size: PositiveInt = Field(
        default=5,
        description="SQLAlchemy connection pool size",
    )
    mssql_max_overflow: int = Field(
        default=2,
        ge=0,
        description="SQLAlchemy max overflow connections",
    )
    mssql_pool_recycle_seconds: PositiveInt = Field(
        default=1800,
        description="SQLAlchemy connection recycle in seconds",
    )
    mssql_pool_pre_ping: bool = Field(
        default=True,
        description="SQLAlchemy pre-ping connection liveness check",
    )
    mssql_trust_server_certificate: bool = Field(
        default=False,
        description="Trust SQL Server certificate without CA validation (local development only)",
    )

    # IIS / W3C Log Reader Configuration (Gate 7A.4A)
    # Default is disabled with NO hardcoded site/directory path.
    # When enabled, an exact valid directory for the SuperOffice IIS site is required.
    iis_log_enabled: bool = Field(
        default=False,
        description="Whether the SuperOffice IIS W3C log reader is enabled",
    )
    iis_log_path: Path | None = Field(
        default=None,
        description="Exact W3C log directory for SuperOffice IIS site (e.g. W3SVC<site-id>)",
    )
    iis_max_files: PositiveInt = Field(
        default=3,
        description="Maximum candidate W3C log files to inspect per search (canonical: 3)",
    )
    iis_max_scan_bytes: PositiveInt = Field(
        default=33_554_432,
        description="Maximum total scan bytes across files (canonical: 32 MiB / 33,554,432 bytes)",
    )
    iis_scan_timeout_seconds: float = Field(
        default=10.0,
        gt=0.0,
        description="Maximum wall-clock scan timeout in seconds (canonical: 10.0s)",
    )
    iis_read_chunk_bytes: PositiveInt = Field(
        default=131_072,
        description="Reverse read chunk size in bytes (canonical: 128 KiB / 131,072 bytes)",
    )
    iis_default_lookback_minutes: PositiveInt = Field(
        default=1440,
        description="Default lookback in minutes if no start_time (canonical: 24h / 1440m)",
    )
    iis_max_lookback_hours: PositiveInt = Field(
        default=72,
        description="Maximum allowable search lookback in hours (canonical: 72h)",
    )
    iis_max_line_bytes: PositiveInt = Field(
        default=8192,
        description="Maximum logical W3C line size in bytes (canonical: 8 KiB / 8,192 bytes)",
    )

    security: SecuritySettings = SecuritySettings()
    logging: LoggingSettings = LoggingSettings()
