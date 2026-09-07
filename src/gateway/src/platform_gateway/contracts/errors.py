"""Gateway error models inheriting from platform_core error hierarchy."""

from typing import Any

from platform_core.errors import (
    IntegrationError,
    ResourceNotFoundError,
)
from platform_core.errors import (
    ValidationError as PlatformValidationError,
)


class GatewayRoutingError(IntegrationError):
    """Base error for Gateway routing failures."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "GATEWAY_ROUTING_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            system_name="MCPGateway",
            error_code=error_code,
            details=details,
        )


class RouteNotFoundError(ResourceNotFoundError):
    """Raised when an unknown tool route is requested from the routing table."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            resource_type="ToolRoute",
            identifier=tool_name,
        )


class DuplicateRouteError(PlatformValidationError):
    """Raised when attempting to register duplicate tool routes in the routing table."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message)


class GatewayDispatchError(IntegrationError):
    """Raised when transport dispatch to a downstream MCP server fails."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "GATEWAY_DISPATCH_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            system_name="MCPGateway",
            error_code=error_code,
            details=details,
        )
