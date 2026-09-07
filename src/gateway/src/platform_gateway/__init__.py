"""Platform Gateway package for perimeter security, authentication, and Streamable HTTP routing."""

from platform_gateway.adapters.http_dispatcher import HttpToolDispatcher
from platform_gateway.registry import GatewayBackendRegistry, create_default_routing_table
from platform_gateway.server.app import create_gateway_app
from platform_gateway.services.gateway_service import GatewayApplicationService
from platform_gateway.settings import GatewayAppSettings

__all__ = [
    "GatewayAppSettings",
    "GatewayApplicationService",
    "GatewayBackendRegistry",
    "HttpToolDispatcher",
    "create_default_routing_table",
    "create_gateway_app",
]
