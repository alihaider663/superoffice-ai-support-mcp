"""Protocol interfaces for Gateway transport dispatch."""

from typing import Protocol, runtime_checkable

from platform_gateway.contracts.dispatch import GatewayDispatchRequest, GatewayDispatchResponse
from platform_gateway.contracts.routing import ToolRouteDefinition


@runtime_checkable
class StreamableHttpDispatcher(Protocol):
    """Protocol for Streamable HTTP transport dispatchers communicating with downstream MCP servers.

    Adheres to ADR 007 (Streamable HTTP Transport).
    """

    async def dispatch(
        self,
        route: ToolRouteDefinition,
        request: GatewayDispatchRequest,
    ) -> GatewayDispatchResponse:
        """Dispatch a normalized request to the target MCP server via Streamable HTTP.

        Raises:
            GatewayDispatchError: If transport communication with downstream server fails.
        """
        ...
