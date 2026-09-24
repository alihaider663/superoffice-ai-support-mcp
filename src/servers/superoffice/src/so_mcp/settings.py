import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, HttpUrl, PositiveInt, SecretStr, model_validator
from pydantic_settings import SettingsConfigDict

from platform_config.base import BasePlatformSettings
from platform_config.logging import LoggingSettings
from platform_config.security import SecuritySettings


class SuperOfficeServerSettings(BasePlatformSettings):
    """Configuration for the SuperOffice CRM MCP Server."""

    model_config = SettingsConfigDict(
        env_prefix="SUPEROFFICE_",
        env_file=".env",
        extra="ignore",
    )

    api_url: HttpUrl = Field(
        default=HttpUrl("https://localhost/SuperOffice"),
        description="Base URL of SuperOffice REST WebAPI",
    )
    username: str = Field(
        default="admin",
        description="SuperOffice API User account",
    )
    password: SecretStr = Field(
        default=SecretStr("insecure-dev-placeholder"),
        description="SuperOffice API User password",
    )
    port: PositiveInt = Field(
        default=8001,
        description="Internal Streamable HTTP listener port",
    )
    timeout_seconds: PositiveInt = Field(
        default=30,
        description="HTTP Request Timeout",
    )
    allow_self_signed_cert: bool = Field(
        default=False,
        description="Allow self-signed TLS certificates",
    )

    security: SecuritySettings = SecuritySettings()
    logging: LoggingSettings = LoggingSettings()


class SuperOfficeCodebaseSyncSettings(BasePlatformSettings):
    """Configuration for the SuperOffice Codebase Synchronization Engine."""

    model_config = SettingsConfigDict(
        env_prefix="SUPEROFFICE_",
        env_file=".env",
        extra="ignore",
    )

    @model_validator(mode="before")
    @classmethod
    def _fallback_from_diagnostics_env(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if (not data.get("mssql_host") or data.get("mssql_host") == "localhost") and (
                "DIAGNOSTICS_MSSQL_HOST" in os.environ
            ):
                data["mssql_host"] = os.environ["DIAGNOSTICS_MSSQL_HOST"]
            if (not data.get("mssql_port") or data.get("mssql_port") == 1433) and (
                "DIAGNOSTICS_MSSQL_PORT" in os.environ
            ):
                data["mssql_port"] = int(os.environ["DIAGNOSTICS_MSSQL_PORT"])
            if (not data.get("mssql_database") or data.get("mssql_database") == "SuperOffice") and (
                "DIAGNOSTICS_MSSQL_DATABASE" in os.environ
            ):
                data["mssql_database"] = os.environ["DIAGNOSTICS_MSSQL_DATABASE"]
            if (not data.get("mssql_user") or data.get("mssql_user") == "so_readonly_user") and (
                "DIAGNOSTICS_MSSQL_USER" in os.environ
            ):
                data["mssql_user"] = os.environ["DIAGNOSTICS_MSSQL_USER"]
            if (
                not data.get("mssql_password")
                or str(data.get("mssql_password")) == "insecure-dev-placeholder"
            ) and ("DIAGNOSTICS_MSSQL_PASSWORD" in os.environ):
                data["mssql_password"] = os.environ["DIAGNOSTICS_MSSQL_PASSWORD"]
        return data

    codebase_local_path: Path = Field(
        default=Path("F:/CodeBase_SuperOffice"),
        description="Local directory path to store mirrored SuperOffice scripts and schemas",
    )
    crmscript_sync_endpoint: str = Field(
        default="scripts/customer.fcgi?action=safeParse&includeId=",
        description="Relative or absolute URL/endpoint for CRMScript query handler",
    )
    sync_mode: Literal["http", "mssql"] = Field(
        default="http",
        description=(
            "Extraction mode: 'http' via CRMScript handler, "
            "or 'mssql' via direct database connection"
        ),
    )
    sync_batch_size: PositiveInt = Field(
        default=100,
        description="Batch size for pagination during sync",
    )
    api_url: HttpUrl = Field(
        default=HttpUrl("https://localhost/SuperOffice"),
        description="Base URL of SuperOffice instance",
    )
    username: str = Field(
        default="admin",
        description="SuperOffice API User account",
    )
    password: SecretStr = Field(
        default=SecretStr("insecure-dev-placeholder"),
        description="SuperOffice API User password",
    )
    allow_self_signed_cert: bool = Field(
        default=False,
        description="Allow self-signed TLS certificates",
    )
    mssql_host: str = Field(
        default="localhost",
        description="MSSQL database hostname or IP address for direct sync",
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
    mssql_trust_server_certificate: bool = Field(
        default=True,
        description="Trust SQL Server certificate without CA validation",
    )
