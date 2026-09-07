"""SuperOffice CRM MCP Server configuration."""

from pydantic import Field, HttpUrl, PositiveInt, SecretStr
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
