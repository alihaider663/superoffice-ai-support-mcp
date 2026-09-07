"""Gateway runtime application configuration."""

from platform_config.gateway import GatewaySettings
from platform_config.logging import LoggingSettings
from platform_config.security import SecuritySettings


class GatewayAppSettings(GatewaySettings):
    """Aggregated settings container for the Gateway process."""

    security: SecuritySettings = SecuritySettings()
    logging: LoggingSettings = LoggingSettings()
