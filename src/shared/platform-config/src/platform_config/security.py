"""Security and authorization typed configuration."""

from pydantic import Field, PositiveInt, SecretStr
from pydantic_settings import SettingsConfigDict

from platform_config.base import BasePlatformSettings


class SecuritySettings(BasePlatformSettings):
    """Configuration for authentication, RBAC, and PII masking."""

    model_config = SettingsConfigDict(
        env_prefix="SECURITY_",
        env_file=".env",
        extra="ignore",
    )

    enable_auth: bool = Field(
        default=True,
        description="Enforce caller token authentication at the Gateway",
    )
    jwt_secret_key: SecretStr = Field(
        default=SecretStr("insecure-placeholder-key-for-local-dev-only-change-in-prod"),
        description="Cryptographic key for validating security tokens",
    )
    token_expiration_seconds: PositiveInt = Field(
        default=3600,
        description="Session security token lifetime in seconds",
    )
    enable_pii_redaction: bool = Field(
        default=True,
        description="Enable real-time regex/contextual PII scrubbing on all tool responses",
    )
    allow_attachment_downloads: bool = Field(
        default=False,
        description="Global kill-switch for raw ticket/mail attachment content retrieval",
    )
