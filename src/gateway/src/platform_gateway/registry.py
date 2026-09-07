"""Gateway backend server registry, routing table construction, and 3-way inventory validation."""

from platform_config.gateway import GatewaySettings
from platform_core.errors import ConfigurationError
from platform_gateway.contracts.errors import GatewayRoutingError
from platform_gateway.contracts.routing import (
    GatewayRoutingTable,
    TargetServer,
    ToolRouteDefinition,
)
from platform_security.rbac import RbacPolicySchema


class GatewayBackendRegistry:
    """Registry mapping trusted TargetServer identifiers to configured Streamable HTTP endpoints.

    SSRF / Open-Proxy Invariant:
    Downstream destination URLs are strictly resolved from immutable Gateway configuration.
    Caller-supplied URLs, hosts, or schemes are never accepted or evaluated.
    """

    def __init__(self, settings: GatewaySettings) -> None:
        self._settings = settings
        self._endpoints: dict[TargetServer, str] = {
            TargetServer.SUPEROFFICE: str(settings.superoffice_mcp_url).rstrip("/"),
            TargetServer.DIAGNOSTICS: str(settings.diagnostics_mcp_url).rstrip("/"),
            TargetServer.KNOWLEDGE: str(settings.knowledge_mcp_url).rstrip("/"),
            TargetServer.INFRASTRUCTURE: str(settings.infrastructure_mcp_url).rstrip("/"),
            TargetServer.INVESTIGATION: str(settings.investigation_mcp_url).rstrip("/"),
        }

    def get_server_url(self, target_server: TargetServer) -> str:
        """Resolve the trusted configured base URL for a target server.

        Raises:
            GatewayRoutingError: If the target server is unknown or unconfigured.
        """
        if not isinstance(target_server, TargetServer) or target_server not in self._endpoints:
            raise GatewayRoutingError(
                f"Unknown or unconfigured target server '{target_server}'.",
                error_code="GATEWAY_UNKNOWN_SERVER",
                details={"target_server": str(target_server)},
            )
        return self._endpoints[target_server]


def create_default_routing_table() -> GatewayRoutingTable:
    """Construct the canonical GatewayRoutingTable registering all approved platform tools.

    Separation of Concerns:
    This routing table contains ONLY transport metadata (tool_name, target_server, endpoint_path)
    for approved and contract-defined domain capabilities.
    """
    canonical_routes: list[ToolRouteDefinition] = [
        # Knowledge MCP Tools (L1)
        ToolRouteDefinition(
            tool_name="search_knowledge",
            target_server=TargetServer.KNOWLEDGE,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="get_runbook",
            target_server=TargetServer.KNOWLEDGE,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="find_known_issues",
            target_server=TargetServer.KNOWLEDGE,
            endpoint_path="/mcp",
        ),
        # SuperOffice MCP Tools (L1 Approved Read-Only Operations)
        ToolRouteDefinition(
            tool_name="get_ticket",
            target_server=TargetServer.SUPEROFFICE,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="search_tickets",
            target_server=TargetServer.SUPEROFFICE,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="get_ticket_messages",
            target_server=TargetServer.SUPEROFFICE,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="list_attachments",
            target_server=TargetServer.SUPEROFFICE,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="get_company",
            target_server=TargetServer.SUPEROFFICE,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="find_companies",
            target_server=TargetServer.SUPEROFFICE,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="get_person",
            target_server=TargetServer.SUPEROFFICE,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="find_persons",
            target_server=TargetServer.SUPEROFFICE,
            endpoint_path="/mcp",
        ),
        # Diagnostics MCP Tools (L2 & L3)
        ToolRouteDefinition(
            tool_name="get_database_health",
            target_server=TargetServer.DIAGNOSTICS,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="find_slow_queries",
            target_server=TargetServer.DIAGNOSTICS,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="get_ticket_diagnostic_record",
            target_server=TargetServer.DIAGNOSTICS,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="search_logs",
            target_server=TargetServer.DIAGNOSTICS,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="find_deadlocks",
            target_server=TargetServer.DIAGNOSTICS,
            endpoint_path="/mcp",
        ),
        ToolRouteDefinition(
            tool_name="find_blocking_sessions",
            target_server=TargetServer.DIAGNOSTICS,
            endpoint_path="/mcp",
        ),
        # Investigation MCP Tools (L3 Composite Investigation)
        ToolRouteDefinition(
            tool_name="investigate_incident",
            target_server=TargetServer.INVESTIGATION,
            endpoint_path="/mcp",
        ),
    ]
    return GatewayRoutingTable.from_routes(canonical_routes)


def validate_routes_against_rbac(
    routing_table: GatewayRoutingTable,
    policy: RbacPolicySchema,
) -> None:
    """Enforce startup security invariant: all registered routes must have RBAC rules.

    Raises:
        ConfigurationError: If any routable tool lacks an RBAC policy entry.
    """
    missing_rbac = [
        tool_name for tool_name in routing_table.routes if tool_name not in policy.tools
    ]
    if missing_rbac:
        raise ConfigurationError(
            f"Security Invariant Violation: Routable tools missing RBAC entries: {missing_rbac}",
            details={"missing_tools": missing_rbac},
        )


def validate_3way_tool_inventory(
    routing_table: GatewayRoutingTable,
    policy: RbacPolicySchema,
    backend_tool_names: set[str],
) -> None:
    """Verify complete 3-way consistency across Routes, RBAC Policy, and Backend Registrations.

    Invariants:
    1. Every Gateway Route has an RBAC rule.
    2. Every Gateway Route is registered in a backend MCP server.
    3. Every registered backend tool is mapped in Gateway routes.
    """
    validate_routes_against_rbac(routing_table, policy)

    route_names = set(routing_table.routes.keys())
    missing_in_backend = route_names - backend_tool_names
    if missing_in_backend:
        raise ConfigurationError(
            "Inventory Inconsistency: Gateway routes missing backend implementation: "
            f"{sorted(missing_in_backend)}",
            details={"missing_in_backend": list(missing_in_backend)},
        )

    unrouted_in_backend = backend_tool_names - route_names
    if unrouted_in_backend:
        raise ConfigurationError(
            f"Inventory Inconsistency: Backend tools missing Gateway routes: "
            f"{sorted(unrouted_in_backend)}",
            details={"unrouted_in_backend": list(unrouted_in_backend)},
        )
