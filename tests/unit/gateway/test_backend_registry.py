"""Unit tests for GatewayBackendRegistry and default routing table construction."""

import pytest
from pydantic import HttpUrl

from platform_config.gateway import GatewaySettings
from platform_core.errors import ConfigurationError
from platform_gateway.contracts.errors import GatewayRoutingError
from platform_gateway.contracts.routing import TargetServer, ToolRouteDefinition
from platform_gateway.registry import (
    GatewayBackendRegistry,
    create_default_routing_table,
    validate_3way_tool_inventory,
    validate_routes_against_rbac,
)
from platform_security.rbac import RbacPolicySchema, ToolPermissionRule


@pytest.fixture
def mock_settings() -> GatewaySettings:
    """Create test gateway settings."""
    return GatewaySettings(
        superoffice_mcp_url=HttpUrl("http://so-internal:8001"),
        diagnostics_mcp_url=HttpUrl("http://diag-internal:8002"),
        knowledge_mcp_url=HttpUrl("http://kb-internal:8003"),
        infrastructure_mcp_url=HttpUrl("http://infra-internal:8004"),
    )


def test_registry_resolves_all_target_servers(mock_settings: GatewaySettings) -> None:
    """Registry correctly maps TargetServer enum values to configured URLs."""
    registry = GatewayBackendRegistry(mock_settings)

    assert registry.get_server_url(TargetServer.SUPEROFFICE) == "http://so-internal:8001"
    assert registry.get_server_url(TargetServer.DIAGNOSTICS) == "http://diag-internal:8002"
    assert registry.get_server_url(TargetServer.KNOWLEDGE) == "http://kb-internal:8003"
    assert registry.get_server_url(TargetServer.INFRASTRUCTURE) == "http://infra-internal:8004"


def test_registry_rejects_unknown_server(mock_settings: GatewaySettings) -> None:
    """Registry raises GatewayRoutingError when an unconfigured target is queried."""
    registry = GatewayBackendRegistry(mock_settings)

    with pytest.raises(GatewayRoutingError) as exc_info:
        registry.get_server_url("UNKNOWN_TARGET")  # type: ignore[arg-type]
    assert "Unknown or unconfigured target server" in str(exc_info.value)


def test_default_routing_table_contains_all_domains() -> None:
    """Default routing table maps tools across approved target domains."""
    table = create_default_routing_table()

    # Knowledge
    assert table.has_route("search_knowledge")
    assert table.get_route("search_knowledge").target_server == TargetServer.KNOWLEDGE

    # SuperOffice
    assert table.has_route("get_ticket")
    assert table.get_route("get_ticket").target_server == TargetServer.SUPEROFFICE

    # Diagnostics
    assert table.has_route("find_slow_queries")
    assert table.get_route("find_slow_queries").target_server == TargetServer.DIAGNOSTICS

    # Investigation
    assert table.has_route("investigate_incident")
    assert table.get_route("investigate_incident").target_server == TargetServer.INVESTIGATION

    # SuperOffice Codebase Sync & Extra Tables
    assert table.has_route("sync_codebase")
    assert table.get_route("sync_codebase").target_server == TargetServer.SUPEROFFICE
    assert table.has_route("list_extra_tables")
    assert table.get_route("list_extra_tables").target_server == TargetServer.SUPEROFFICE
    assert table.has_route("get_extra_table_schema")
    assert table.get_route("get_extra_table_schema").target_server == TargetServer.SUPEROFFICE
    assert table.has_route("query_extra_table")
    assert table.get_route("query_extra_table").target_server == TargetServer.SUPEROFFICE
    assert table.has_route("get_ticket_audit_trail")
    assert table.get_route("get_ticket_audit_trail").target_server == TargetServer.SUPEROFFICE
    assert table.has_route("search_codebase")
    assert table.get_route("search_codebase").target_server == TargetServer.SUPEROFFICE
    assert table.has_route("get_codebase_file")
    assert table.get_route("get_codebase_file").target_server == TargetServer.SUPEROFFICE
    assert table.has_route("get_screen_details")
    assert table.get_route("get_screen_details").target_server == TargetServer.SUPEROFFICE
    assert table.has_route("get_associate_details")
    assert table.get_route("get_associate_details").target_server == TargetServer.SUPEROFFICE
    assert table.has_route("get_ticket_metadata_lists")
    assert table.get_route("get_ticket_metadata_lists").target_server == TargetServer.SUPEROFFICE
    assert table.has_route("list_system_events_and_triggers")
    assert (
        table.get_route("list_system_events_and_triggers").target_server == TargetServer.SUPEROFFICE
    )

    # Assert 29 total approved routes
    assert len(table.routes) == 29


def test_validate_routes_against_rbac_detects_missing_tool() -> None:
    """Cross-validation between routing table and RBAC schema detects unmapped tools."""
    table = create_default_routing_table()

    dummy_policy = RbacPolicySchema(
        tools={
            "search_knowledge": ToolPermissionRule(minimum_role="L1"),
        }
    )

    with pytest.raises(ConfigurationError) as exc_info:
        validate_routes_against_rbac(table, dummy_policy)
    assert "Routable tools missing RBAC entries" in str(exc_info.value)


def test_validate_routes_against_rbac_passes_when_all_tools_present() -> None:
    """Cross-validation succeeds when every routable tool has an RBAC rule."""
    table = create_default_routing_table()
    full_tools = {name: ToolPermissionRule(minimum_role="L1") for name in table.routes}
    policy = RbacPolicySchema(tools=full_tools)
    validate_routes_against_rbac(table, policy)


def test_validate_3way_tool_inventory_detects_missing_backend() -> None:
    """3-way cross validation raises ConfigurationError if a route lacks backend registration."""
    table = create_default_routing_table()
    full_tools = {name: ToolPermissionRule(minimum_role="L1") for name in table.routes}
    policy = RbacPolicySchema(tools=full_tools)

    # Missing get_ticket in backend registrations
    incomplete_backend = set(table.routes.keys()) - {"get_ticket"}
    with pytest.raises(ConfigurationError) as exc_info:
        validate_3way_tool_inventory(table, policy, incomplete_backend)
    assert "Gateway routes missing backend implementation" in str(exc_info.value)


def test_validate_3way_tool_inventory_passes_when_fully_synced() -> None:
    """3-way cross validation passes when routes, RBAC, and backend registrations match 100%."""
    table = create_default_routing_table()
    full_tools = {name: ToolPermissionRule(minimum_role="L1") for name in table.routes}
    policy = RbacPolicySchema(tools=full_tools)
    backend_tools = set(table.routes.keys())

    validate_3way_tool_inventory(table, policy, backend_tools)


def test_tool_route_definition_has_no_rbac_fields() -> None:
    """Ensure ToolRouteDefinition remains transport-only with zero authorization fields."""
    forbidden = {
        "minimum_role",
        "required_role",
        "permissions",
        "production_write",
        "attachment_access",
    }
    fields = set(ToolRouteDefinition.model_fields.keys())
    assert not forbidden.intersection(fields)
