"""Gateway contract definitions, DTOs, routing models, and protocol interfaces."""

from platform_gateway.contracts.dispatch import (
    GatewayDispatchRequest,
    GatewayDispatchResponse,
    SanitizedErrorPayload,
)
from platform_gateway.contracts.errors import (
    DuplicateRouteError,
    GatewayDispatchError,
    GatewayRoutingError,
    RouteNotFoundError,
)
from platform_gateway.contracts.interfaces import (
    StreamableHttpDispatcher,
)
from platform_gateway.contracts.routing import (
    GatewayRoutingTable,
    TargetServer,
    ToolRouteDefinition,
)
from platform_gateway.contracts.types import (
    JsonArray,
    JsonObject,
    JsonPrimitive,
    JsonValue,
    is_json_compatible,
)

__all__ = [
    "DuplicateRouteError",
    "GatewayDispatchError",
    "GatewayDispatchRequest",
    "GatewayDispatchResponse",
    "GatewayRoutingError",
    "GatewayRoutingTable",
    "JsonArray",
    "JsonObject",
    "JsonPrimitive",
    "JsonValue",
    "RouteNotFoundError",
    "SanitizedErrorPayload",
    "StreamableHttpDispatcher",
    "TargetServer",
    "ToolRouteDefinition",
    "is_json_compatible",
]
