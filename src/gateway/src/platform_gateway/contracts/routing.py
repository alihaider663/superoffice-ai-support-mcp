"""Gateway routing models, target server enumeration, and immutable routing table."""

from collections.abc import Sequence
from enum import StrEnum

from pydantic import Field

from platform_core.models import PlatformBaseModel
from platform_gateway.contracts.errors import DuplicateRouteError, RouteNotFoundError


class TargetServer(StrEnum):
    """Approved target MCP servers in the platform architecture.

    Note: Detailed Infrastructure adapter contracts are deferred, but Infrastructure
    remains an approved target server in the four-server Gateway architecture.
    """

    SUPEROFFICE = "SUPEROFFICE"
    DIAGNOSTICS = "DIAGNOSTICS"
    KNOWLEDGE = "KNOWLEDGE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    INVESTIGATION = "INVESTIGATION"


class ToolRouteDefinition(PlatformBaseModel):
    """Transport-only route definition mapping a canonical tool name to a downstream MCP server.

    CRITICAL ARCHITECTURAL INVARIANT:
    Authorization rules (RBAC minimum_role, permissions, production_write, attachment_access)
    are strictly managed in platform_security / tool_permissions.yaml and must NEVER be
    placed inside ToolRouteDefinition.
    """

    tool_name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Canonical capability/tool name",
    )
    target_server: TargetServer = Field(
        ...,
        description="Target downstream MCP server fault domain",
    )
    endpoint_path: str = Field(
        default="/mcp",
        min_length=1,
        max_length=256,
        description="Downstream Streamable HTTP endpoint path",
    )
    route_timeout_seconds: float | None = Field(
        default=None,
        ge=0.1,
        le=120.0,
        description="Optional transport timeout override for this route",
    )


class GatewayRoutingTable(PlatformBaseModel):
    """Immutable routing table mapping canonical tool names to ToolRouteDefinitions."""

    routes: dict[str, ToolRouteDefinition] = Field(
        default_factory=dict,
        description="Mapping of tool name to route definition",
    )

    @classmethod
    def from_routes(cls, routes: Sequence[ToolRouteDefinition]) -> "GatewayRoutingTable":
        """Construct an immutable GatewayRoutingTable from a sequence of route definitions.

        Raises:
            DuplicateRouteError: If duplicate canonical tool names are provided.
        """
        route_map: dict[str, ToolRouteDefinition] = {}
        for route in routes:
            normalized_name = route.tool_name.strip()
            if normalized_name in route_map:
                raise DuplicateRouteError(
                    f"Duplicate route registration for tool '{normalized_name}'."
                )
            route_map[normalized_name] = route
        return cls(routes=route_map)

    def get_route(self, tool_name: str) -> ToolRouteDefinition:
        """Lookup route definition by canonical tool name.

        Raises:
            RouteNotFoundError: If the tool is not registered in the routing table.
        """
        normalized_name = tool_name.strip()
        if normalized_name not in self.routes:
            raise RouteNotFoundError(normalized_name)
        return self.routes[normalized_name]

    def has_route(self, tool_name: str) -> bool:
        """Check if a tool is registered in the routing table."""
        return tool_name.strip() in self.routes
