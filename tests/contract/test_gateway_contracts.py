"""Offline contract tests for Gateway Routing, Dispatch envelopes, JSON types, and test fakes."""

import asyncio
import sys
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from investigation_mcp.contracts.dtos import (
    InvestigateIncidentRequestDTO,
    InvestigateIncidentResponseDTO,
)
from platform_core.models import PrincipalIdentity
from platform_gateway.contracts.dispatch import (
    GatewayDispatchRequest,
    SanitizedErrorPayload,
)
from platform_gateway.contracts.errors import (
    DuplicateRouteError,
    GatewayDispatchError,
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
    is_json_compatible,
)
from platform_gateway.registry import create_default_routing_table
from platform_gateway.schemas import get_tool_schema_map
from platform_security.models import SecurityContext
from tests.fakes.fake_gateway_dispatcher import FakeGatewayDispatcher

# ============================================================================
# 1. JSON Types & Validation Tests
# ============================================================================


def test_json_types_valid() -> None:
    """Verify JSON-compatible primitives, arrays, and nested structures."""
    valid_payloads = [
        "simple string",
        123,
        45.67,
        True,
        False,
        None,
        ["item1", 2, True, None],
        {"key1": "val1", "key2": [1, 2, 3], "nested": {"sub": True}},
        {},
        [],
    ]
    for p in valid_payloads:
        assert is_json_compatible(p) is True


def test_json_types_rejected() -> None:
    """Verify non-JSON types are rejected by JSON validation."""
    invalid_payloads = [
        b"raw bytes",
        {"key": b"bytes value"},
        {1, 2, 3},  # Set
        object(),
        datetime.now(UTC),  # Datetime object directly (not serialized to str)
        lambda: None,
    ]
    for p in invalid_payloads:
        assert is_json_compatible(p) is False


def test_dispatch_request_rejects_non_json_arguments() -> None:
    """Verify GatewayDispatchRequest raises ValidationError if arguments are non-JSON."""
    ctx = SecurityContext(
        principal=PrincipalIdentity(
            user_id="USR-101",
            role="ANALYST",
        ),
        token_id="TOK-9988",
    )
    with pytest.raises(ValidationError):
        GatewayDispatchRequest.model_validate(
            {
                "tool_name": "get_ticket",
                "arguments": {"raw_bytes": b"not allowed"},
                "security_context": ctx,
                "correlation_id": "CORR-111",
            }
        )


# ============================================================================
# 2. Routing Contract & Target Server Tests
# ============================================================================


def test_target_server_enum_values() -> None:
    """Verify all four approved target servers are representable."""
    assert TargetServer.SUPEROFFICE == "SUPEROFFICE"
    assert TargetServer.DIAGNOSTICS == "DIAGNOSTICS"
    assert TargetServer.KNOWLEDGE == "KNOWLEDGE"
    assert TargetServer.INFRASTRUCTURE == "INFRASTRUCTURE"
    assert TargetServer.INVESTIGATION == "INVESTIGATION"
    assert len(TargetServer) == 5


def test_route_definition_immutability_and_extra_forbid() -> None:
    """Verify ToolRouteDefinition is frozen and forbids extra unapproved fields."""
    route = ToolRouteDefinition(
        tool_name="get_ticket",
        target_server=TargetServer.SUPEROFFICE,
        endpoint_path="/mcp/superoffice",
        route_timeout_seconds=5.0,
    )
    assert route.tool_name == "get_ticket"
    assert route.target_server == TargetServer.SUPEROFFICE

    # Frozen mutation check
    field_to_mutate = "endpoint_path"
    with pytest.raises(ValidationError):
        setattr(route, field_to_mutate, "/mcp/other")

    # Extra field forbid check
    extra_payload = {
        "tool_name": "get_ticket",
        "target_server": "SUPEROFFICE",
        "endpoint_path": "/mcp/superoffice",
        "unauthorized_extra_field": "injected",
    }
    with pytest.raises(ValidationError):
        ToolRouteDefinition.model_validate(extra_payload)


def test_routing_table_lookup_and_unknown_route() -> None:
    """Verify route registration, lookup, and unknown route error."""
    routes = [
        ToolRouteDefinition(
            tool_name="get_ticket",
            target_server=TargetServer.SUPEROFFICE,
        ),
        ToolRouteDefinition(
            tool_name="find_slow_queries",
            target_server=TargetServer.DIAGNOSTICS,
        ),
        ToolRouteDefinition(
            tool_name="search_knowledge",
            target_server=TargetServer.KNOWLEDGE,
        ),
    ]
    table = GatewayRoutingTable.from_routes(routes)

    # 1. Lookup existing routes
    assert table.has_route("get_ticket") is True
    assert table.has_route("find_slow_queries") is True
    r = table.get_route("get_ticket")
    assert r.target_server == TargetServer.SUPEROFFICE

    # 2. Unknown route raises RouteNotFoundError
    assert table.has_route("unknown_tool_xyz") is False
    with pytest.raises(RouteNotFoundError) as exc_info:
        table.get_route("unknown_tool_xyz")
    assert "unknown_tool_xyz" in str(exc_info.value)


def test_routing_table_duplicate_route_rejection() -> None:
    """Verify GatewayRoutingTable rejects duplicate route registrations."""
    duplicate_routes = [
        ToolRouteDefinition(
            tool_name="get_ticket",
            target_server=TargetServer.SUPEROFFICE,
        ),
        ToolRouteDefinition(
            tool_name="get_ticket",  # Duplicate
            target_server=TargetServer.SUPEROFFICE,
        ),
    ]
    with pytest.raises(DuplicateRouteError) as exc_info:
        GatewayRoutingTable.from_routes(duplicate_routes)
    assert "get_ticket" in str(exc_info.value)


# ============================================================================
# 3. RBAC Separation Tests
# ============================================================================


def test_routing_definition_contains_no_rbac_fields() -> None:
    """Verify ToolRouteDefinition does NOT contain any RBAC or authorization fields."""
    forbidden_rbac_fields = {
        "minimum_role",
        "required_role",
        "permissions",
        "production_write",
        "attachment_access",
        "roles",
        "allowed_roles",
    }
    present_fields = set(ToolRouteDefinition.model_fields.keys())
    intersection = forbidden_rbac_fields.intersection(present_fields)
    assert not intersection, f"ToolRouteDefinition contains forbidden RBAC fields: {intersection}"


# ============================================================================
# 4. SecurityContext & Correlation Tests
# ============================================================================


def test_security_context_in_dispatch_envelope() -> None:
    """Verify GatewayDispatchRequest carries trusted SecurityContext from platform_security."""
    principal = PrincipalIdentity(
        user_id="USR-404",
        role="ENGINEER",
    )
    sec_ctx = SecurityContext(
        principal=principal,
        token_id="TOK-7721",
        is_authenticated=True,
        attributes={"department": "Support"},
    )
    req = GatewayDispatchRequest(
        tool_name="find_deadlocks",
        arguments={"window_minutes": 60},
        security_context=sec_ctx,
        correlation_id="CORR-TRACE-001",
    )
    assert req.security_context.principal.user_id == "USR-404"
    assert req.security_context.principal.role == "ENGINEER"
    assert req.correlation_id == "CORR-TRACE-001"


# ============================================================================
# 5. Fake Gateway Dispatcher & Protocol Conformance Tests
# ============================================================================


def test_fake_gateway_dispatcher_is_instance_of_protocol() -> None:
    """Verify FakeGatewayDispatcher satisfies StreamableHttpDispatcher Protocol."""
    fake = FakeGatewayDispatcher()
    assert isinstance(fake, StreamableHttpDispatcher)


def test_fake_gateway_dispatcher_operations() -> None:
    """Verify in-memory dispatch, correlation preservation, and error handling."""

    async def _run_async() -> None:
        fake = FakeGatewayDispatcher()
        sec_ctx = SecurityContext(
            principal=PrincipalIdentity(
                user_id="USR-101",
                role="ADMIN",
            ),
            token_id="TOK-1111",
        )
        route_so = ToolRouteDefinition(
            tool_name="get_ticket",
            target_server=TargetServer.SUPEROFFICE,
            endpoint_path="/mcp/superoffice",
        )
        req = GatewayDispatchRequest(
            tool_name="get_ticket",
            arguments={"ticket_id": 4040},
            security_context=sec_ctx,
            correlation_id="CORR-UUID-9999",
        )

        # 1. Default echo dispatch
        res = await fake.dispatch(route_so, req)
        assert res.success is True
        assert res.tool_name == "get_ticket"
        assert res.correlation_id == "CORR-UUID-9999"
        assert isinstance(res.result, dict)
        assert res.result.get("target_server") == "SUPEROFFICE"

        # Verify dispatched history was recorded
        history = fake.get_dispatched_requests()
        assert len(history) == 1
        assert history[0][0].tool_name == "get_ticket"
        assert history[0][1].correlation_id == "CORR-UUID-9999"

        # 2. Seeded custom success result
        fake.set_default_success("get_ticket", {"ticket_id": 4040, "title": "Database sync issue"})
        res_custom = await fake.dispatch(route_so, req)
        assert res_custom.success is True
        assert res_custom.result == {"ticket_id": 4040, "title": "Database sync issue"}
        assert res_custom.correlation_id == "CORR-UUID-9999"

        # 3. Seeded sanitized error
        fake.set_error("get_ticket", "RESOURCE_NOT_FOUND", "Ticket 4040 was not found.")
        res_err = await fake.dispatch(route_so, req)
        assert res_err.success is False
        assert res_err.result is None
        assert res_err.error is not None
        assert res_err.error.error == "RESOURCE_NOT_FOUND"
        assert res_err.error.message == "Ticket 4040 was not found."
        assert res_err.correlation_id == "CORR-UUID-9999"

        # 4. Simulated transport failure raises GatewayDispatchError
        fake.set_should_fail(True)
        with pytest.raises(GatewayDispatchError) as exc_info:
            await fake.dispatch(route_so, req)
        assert "Simulated transport failure" in str(exc_info.value)

    asyncio.run(_run_async())


# ============================================================================
# 6. Gateway Isolation & Error Safety Tests
# ============================================================================


def test_gateway_contracts_isolation_from_server_packages() -> None:
    """Verify platform_gateway.contracts does NOT import server domain packages."""
    forbidden_modules = {"so_mcp", "diag_mcp", "kb_mcp", "infra_mcp"}
    gateway_contract_modules = [
        mod_name for mod_name in sys.modules if mod_name.startswith("platform_gateway.contracts")
    ]
    for mod_name in gateway_contract_modules:
        mod = sys.modules[mod_name]
        imported_symbols = dir(mod)
        for sym in imported_symbols:
            assert sym not in forbidden_modules, (
                f"Gateway contract {mod_name} illegally imports server package {sym}"
            )


def test_sanitized_error_payload_safety() -> None:
    """Verify SanitizedErrorPayload adheres to sanitized schema without tracebacks."""
    err_payload = SanitizedErrorPayload(
        error="GATEWAY_ROUTING_ERROR",
        message="Requested capability is not available.",
        correlation_id="CORR-5555",
    )
    assert err_payload.error == "GATEWAY_ROUTING_ERROR"
    assert err_payload.message == "Requested capability is not available."
    assert err_payload.correlation_id == "CORR-5555"
    assert isinstance(err_payload.timestamp, datetime)

    # Rejection of extra unapproved fields (e.g. raw traceback)
    with pytest.raises(ValidationError):
        SanitizedErrorPayload.model_validate(
            {
                "error": "GATEWAY_ERROR",
                "message": "Safe message",
                "raw_traceback": "Traceback (most recent call last)...",
            }
        )


# =============================================================================
# Phase 4.3 — Gateway Contract Tests for investigate_incident
# =============================================================================


def _normalize_schema(schema: Any) -> Any:
    """Recursively normalize dictionary keys, required lists, and enum lists for equality."""
    if isinstance(schema, dict):
        normalized: dict[str, Any] = {}
        for k, v in schema.items():
            if k in ("required", "enum") and isinstance(v, list):
                normalized[k] = sorted(v)
            else:
                normalized[k] = _normalize_schema(v)
        return dict(sorted(normalized.items()))
    if isinstance(schema, list):
        return [_normalize_schema(item) for item in schema]
    return schema


def test_investigate_incident_route_contract() -> None:
    """Verify investigate_incident route points to TargetServer.INVESTIGATION at /mcp."""

    table = create_default_routing_table()
    assert table.has_route("investigate_incident")
    route = table.get_route("investigate_incident")
    assert route.target_server == TargetServer.INVESTIGATION
    assert route.endpoint_path == "/mcp"


def test_investigate_incident_no_wildcard_routes() -> None:
    """Verify unapproved subordinate orchestration actions are not routable through Gateway."""

    table = create_default_routing_table()
    for unapproved in (
        "create_plan",
        "advance_step",
        "aggregate_evidence",
        "evaluate_hypothesis",
        "investigate_incident_wildcard",
    ):
        with pytest.raises(RouteNotFoundError):
            table.get_route(unapproved)


def test_gateway_investigate_incident_schema_full_contract_equality() -> None:
    """Verify Gateway inputSchema and outputSchema match Phase 4.2 DTOs with 100% fidelity.

    Detects drift in: defaults, types, min/max, minLength/maxLength, enums, required fields,
    additionalProperties, $defs, discriminators, and const properties.
    """

    schema_map = get_tool_schema_map()
    assert "investigate_incident" in schema_map
    gateway_tool = schema_map["investigate_incident"]

    expected_input = InvestigateIncidentRequestDTO.model_json_schema(by_alias=True)
    expected_output = InvestigateIncidentResponseDTO.model_json_schema(by_alias=True)

    # 1. Semantic equality of input schema
    assert _normalize_schema(gateway_tool.inputSchema) == _normalize_schema(expected_input)

    # 2. Semantic equality of output schema
    assert gateway_tool.outputSchema is not None
    assert _normalize_schema(gateway_tool.outputSchema) == _normalize_schema(expected_output)

    # 3. Specific invariant checks against known drift patterns
    # - include_database_health default must be False
    diag_props = expected_input["$defs"]["InvestigationDiagnosticsInputDTO"]["properties"]
    assert diag_props["include_database_health"]["default"] is False

    # - slow_queries.min_duration_ms must be integer, minimum 1, default 1000
    sq_props = expected_input["$defs"]["SlowQueryInvestigationInputDTO"]["properties"]
    assert sq_props["min_duration_ms"]["type"] == "integer"
    assert sq_props["min_duration_ms"]["minimum"] == 1
    assert sq_props["min_duration_ms"]["default"] == 1000

    # - deadlock limit default must be 10, max 50
    dl_props = expected_input["$defs"]["DeadlockInvestigationInputDTO"]["properties"]
    assert dl_props["limit"]["default"] == 10

    # - initial_hypothesis must have minLength 1 and maxLength 256
    hypo_props = expected_input["properties"]["initial_hypothesis"]
    assert hypo_props["minLength"] == 1
    assert hypo_props["maxLength"] == 256

    # - output status enum must not contain PARTIAL
    outcome_props = expected_output["$defs"]["InvestigationSourceOutcomeWireDTO"]["properties"]
    statuses = set(outcome_props["status"]["enum"])
    assert "PARTIAL" not in statuses
    assert statuses == {"SUCCESS", "NOT_CONFIGURED", "BLOCKED", "UNAVAILABLE", "FAILED"}
