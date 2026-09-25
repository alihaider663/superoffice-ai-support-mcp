"""Security regression tests for Gateway perimeter defenses."""

import inspect
import time
from unittest.mock import AsyncMock

import jwt
import pytest
from starlette.testclient import TestClient

from investigation_mcp.adapters import diagnostics_mcp_adapter, superoffice_mcp_adapter
from investigation_mcp.adapters.diagnostics_mcp_adapter import (
    TOOL_NAME_DATABASE_HEALTH,
    TOOL_NAME_FIND_DEADLOCKS,
    TOOL_NAME_FIND_SLOW_QUERIES,
    DiagnosticsMcpClientAdapter,
)
from investigation_mcp.adapters.superoffice_mcp_adapter import (
    TOOL_NAME_GET_TICKET,
    SuperOfficeMcpClientAdapter,
)
from investigation_mcp.contracts.dtos import InvestigateIncidentResponseDTO
from platform_config.gateway import GatewaySettings
from platform_core.models import PrincipalIdentity
from platform_gateway.adapters.http_dispatcher import HttpToolDispatcher
from platform_gateway.constants import (
    INTERNAL_HEADER_ATTACHMENT_ACCESS,
    INTERNAL_HEADER_CORRELATION_ID,
    INTERNAL_HEADER_PRODUCTION_WRITE,
    INTERNAL_HEADER_USER_ID,
    INTERNAL_HEADER_USER_ROLE,
)
from platform_gateway.contracts.dispatch import (
    GatewayDispatchRequest,
    GatewayDispatchResponse,
)
from platform_gateway.contracts.errors import GatewayRoutingError
from platform_gateway.contracts.interfaces import StreamableHttpDispatcher
from platform_gateway.contracts.routing import TargetServer, ToolRouteDefinition
from platform_gateway.registry import GatewayBackendRegistry, create_default_routing_table
from platform_gateway.server.app import create_gateway_app
from platform_gateway.services.gateway_service import GatewayApplicationService
from platform_gateway.settings import GatewayAppSettings
from platform_security.jwt import JwtAuthenticator
from platform_security.models import SecurityContext
from platform_security.rbac import YamlPolicyEngine
from platform_security.sanitization import RecursiveOutputSanitizer

TEST_SECRET = "security-test-signing-key-999-32bytes-secure"


def _make_jwt(sub: str = "USR-REGULAR", role: str = "L1", prod_write: bool = False) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "role": role,
        "production_write": prod_write,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, TEST_SECRET, algorithm="HS256")


def test_anti_ssrf_destination_is_immutable() -> None:
    """Caller-supplied URL arguments cannot alter downstream dispatch destination."""
    settings = GatewayAppSettings()
    registry = GatewayBackendRegistry(settings)

    # Attempt to query with arbitrary destination
    with pytest.raises(GatewayRoutingError):
        registry.get_server_url("http://malicious-attacker.com")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_spoofed_headers_are_stripped_and_overwritten_by_gateway() -> None:
    """Caller-supplied internal identity headers are stripped and overwritten."""
    captured_requests: list[GatewayDispatchRequest] = []

    class CapturingDispatcher(StreamableHttpDispatcher):
        async def dispatch(
            self,
            route: ToolRouteDefinition,  # noqa: ARG002
            request: GatewayDispatchRequest,
        ) -> GatewayDispatchResponse:
            captured_requests.append(request)
            return GatewayDispatchResponse(
                tool_name=request.tool_name,
                success=True,
                result={"status": "ok"},
                correlation_id=request.correlation_id,
            )

    dispatcher = CapturingDispatcher()
    routing_table = create_default_routing_table()
    authenticator = JwtAuthenticator(secret_or_key=TEST_SECRET, algorithms=["HS256"])
    authorizer = YamlPolicyEngine()
    sanitizer = RecursiveOutputSanitizer()

    service = GatewayApplicationService(
        routing_table=routing_table,
        dispatcher=dispatcher,
        authenticator=authenticator,
        authorizer=authorizer,
        sanitizer=sanitizer,
    )

    app = create_gateway_app(service=service, routing_table=routing_table)

    token = _make_jwt(sub="GENUINE-USER", role="L1", prod_write=False)

    # Malicious caller injects spoofed headers attempting privilege escalation
    spoofed_headers = {
        "Authorization": f"Bearer {token}",
        "X-User-ID": "ATTACKER-ROOT",
        "X-User-Role": "L3",
        "X-Production-Write": "true",
        "X-Attachment-Access": "true",
        "X-Security-Context": "injected-admin",
        "Accept": "application/json, text/event-stream",
    }

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_ticket",
            "arguments": {"ticket_id": 100},
        },
        "id": 1,
    }

    with TestClient(app) as client:
        res = client.post("/mcp", json=payload, headers=spoofed_headers)
        assert res.status_code == 200

    assert len(captured_requests) == 1
    req = captured_requests[0]

    # Verify security context was built purely from genuine JWT claims
    assert req.security_context.principal.user_id == "GENUINE-USER"
    assert req.security_context.principal.role == "L1"
    assert req.security_context.attributes.get("production_write") is False
    assert req.security_context.attributes.get("attachment_access") is False


def test_protocol_level_authorization_evaluates_tool_name() -> None:
    """Protocol-level router checks tool permission before invoking downstream server."""
    captured_calls: list[str] = []

    class CapturingDispatcher(StreamableHttpDispatcher):
        async def dispatch(
            self,
            route: ToolRouteDefinition,  # noqa: ARG002
            request: GatewayDispatchRequest,
        ) -> GatewayDispatchResponse:
            captured_calls.append(request.tool_name)
            return GatewayDispatchResponse(
                tool_name=request.tool_name,
                success=True,
                result={"status": "ok"},
                correlation_id=request.correlation_id,
            )

    dispatcher = CapturingDispatcher()
    routing_table = create_default_routing_table()
    authenticator = JwtAuthenticator(secret_or_key=TEST_SECRET, algorithms=["HS256"])
    authorizer = YamlPolicyEngine()
    sanitizer = RecursiveOutputSanitizer()

    service = GatewayApplicationService(
        routing_table=routing_table,
        dispatcher=dispatcher,
        authenticator=authenticator,
        authorizer=authorizer,
        sanitizer=sanitizer,
    )

    app = create_gateway_app(service=service, routing_table=routing_table)

    # L1 caller attempts to invoke L3 tool find_deadlocks
    token_l1 = _make_jwt(sub="USR-L1-CALLER", role="L1")
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "find_deadlocks",
            "arguments": {"limit": 5},
        },
        "id": 1,
    }

    with TestClient(app) as client:
        res = client.post(
            "/mcp",
            json=payload,
            headers={
                "Authorization": f"Bearer {token_l1}",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert res.status_code == 200
        assert "INSUFFICIENT_ROLE" in res.text

    # Downstream dispatcher must NOT have been called
    assert len(captured_calls) == 0


# =============================================================================
# Phase 4.3 — Composite Capability Guards, RBAC Dominance, and Header Tests
# =============================================================================


def _create_sec_jwt(
    sub: str = "USR-101",
    role: str = "L1",
    production_write: bool = False,
    attachment_access: bool = False,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "role": role,
        "production_write": production_write,
        "attachment_access": attachment_access,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, TEST_SECRET, algorithm="HS256")


def _discover_adapter_tool_constants() -> set[str]:
    """Dynamically discover all exported TOOL_NAME_* constants from Phase 4.1 adapter modules."""

    discovered: set[str] = set()
    for mod in (superoffice_mcp_adapter, diagnostics_mcp_adapter):
        for name, val in inspect.getmembers(mod):
            if name.startswith("TOOL_NAME_") and isinstance(val, str):
                discovered.add(val)
    return discovered


def test_composite_capability_guard_a_dynamic_discovery() -> None:
    """Guard A: Prove dynamically discovered adapter capability surface equals approved ADR 012 set.

    Fails if a fifth constant/capability is added to either adapter module.
    """
    actual_capabilities = _discover_adapter_tool_constants()
    assert actual_capabilities == {
        "get_ticket",
        "get_ticket_audit_trail",
        "get_database_health",
        "find_slow_queries",
        "find_deadlocks",
        "get_ticket_diagnostic_record",
        "find_blocking_sessions",
        "search_logs",
    }


def test_composite_capability_guard_b_rbac_dominance() -> None:
    """Guard B: Prove composite minimum role and privileges strictly dominate subordinates."""
    actual_capabilities = _discover_adapter_tool_constants()
    policy = YamlPolicyEngine().policy

    assert "investigate_incident" in policy.tools
    composite_rule = policy.tools["investigate_incident"]
    assert composite_rule.minimum_role == "L3"
    assert tuple(composite_rule.requires) == ()

    roles_hierarchy = policy.roles_hierarchy  # {"L1": 1, "L2": 2, "L3": 3}
    composite_weight = roles_hierarchy[composite_rule.minimum_role]

    for sub_name in actual_capabilities:
        assert sub_name in policy.tools, f"Subordinate tool '{sub_name}' missing from RBAC policy"
        sub_rule = policy.tools[sub_name]

        # 1. Role dominance
        sub_weight = roles_hierarchy[sub_rule.minimum_role]
        assert composite_weight >= sub_weight, (
            f"Composite role '{composite_rule.minimum_role}' (weight {composite_weight}) "
            f"does not dominate subordinate '{sub_name}' role '{sub_rule.minimum_role}'"
        )

        # 2. Privilege dominance
        assert set(sub_rule.requires).issubset(set(composite_rule.requires)), (
            f"Composite requires {composite_rule.requires} does not cover {sub_name}"
        )


def test_adapter_outbound_dispatch_invariant() -> None:
    """Verify adapter outbound dispatch calls fixed constants and accepts no arbitrary strings."""
    # Invariant: Neither adapter accepts caller-supplied tool names
    so_sig = inspect.signature(SuperOfficeMcpClientAdapter.get_ticket)
    assert "tool_name" not in so_sig.parameters
    assert "tool" not in so_sig.parameters

    diag_health_sig = inspect.signature(DiagnosticsMcpClientAdapter.get_database_health)
    assert "tool_name" not in diag_health_sig.parameters

    diag_slow_sig = inspect.signature(DiagnosticsMcpClientAdapter.find_slow_queries)
    assert "tool_name" not in diag_slow_sig.parameters

    diag_deadlock_sig = inspect.signature(DiagnosticsMcpClientAdapter.find_deadlocks)
    assert "tool_name" not in diag_deadlock_sig.parameters

    # Assert constants match canonical names
    assert TOOL_NAME_GET_TICKET == "get_ticket"
    assert TOOL_NAME_DATABASE_HEALTH == "get_database_health"
    assert TOOL_NAME_FIND_DEADLOCKS == "find_deadlocks"
    assert TOOL_NAME_FIND_SLOW_QUERIES == "find_slow_queries"


@pytest.mark.asyncio
async def test_investigate_incident_rbac_matrix() -> None:
    """RBAC matrix for investigate_incident: L1/L2 deny, L3 allow, privileges cannot substitute."""
    table = create_default_routing_table()
    dispatcher = AsyncMock(spec=StreamableHttpDispatcher)

    async def _mock_dispatch(
        route: ToolRouteDefinition, request: GatewayDispatchRequest
    ) -> GatewayDispatchResponse:
        _ = route
        return GatewayDispatchResponse(
            tool_name=request.tool_name,
            success=True,
            result={"source_outcomes": [], "evidence": []},
            error=None,
            correlation_id=request.correlation_id,
        )

    dispatcher.dispatch = AsyncMock(side_effect=_mock_dispatch)
    service = GatewayApplicationService(
        routing_table=table,
        dispatcher=dispatcher,
        authenticator=JwtAuthenticator(secret_or_key=TEST_SECRET, algorithms=["HS256"]),
        authorizer=YamlPolicyEngine(),
        sanitizer=RecursiveOutputSanitizer(),
    )

    # 1. L1 caller -> Denied (INSUFFICIENT_ROLE)
    token_l1 = _create_sec_jwt(sub="USR-L1", role="L1")
    res_l1 = await service.handle_tool_call(
        tool_name="investigate_incident",
        arguments={"initial_hypothesis": "Test incident"},
        authorization_header=f"Bearer {token_l1}",
    )
    assert res_l1.success is False
    assert res_l1.error is not None
    assert res_l1.error.error == "INSUFFICIENT_ROLE"

    # 2. L2 caller -> Denied (INSUFFICIENT_ROLE)
    token_l2 = _create_sec_jwt(sub="USR-L2", role="L2")
    res_l2 = await service.handle_tool_call(
        tool_name="investigate_incident",
        arguments={"initial_hypothesis": "Test incident"},
        authorization_header=f"Bearer {token_l2}",
    )
    assert res_l2.success is False
    assert res_l2.error is not None
    assert res_l2.error.error == "INSUFFICIENT_ROLE"

    # 3. L2 caller with both privileges -> Still Denied!
    token_l2_priv = _create_sec_jwt(
        sub="USR-L2-PRIV", role="L2", production_write=True, attachment_access=True
    )
    res_l2_priv = await service.handle_tool_call(
        tool_name="investigate_incident",
        arguments={"initial_hypothesis": "Test incident"},
        authorization_header=f"Bearer {token_l2_priv}",
    )
    assert res_l2_priv.success is False
    assert res_l2_priv.error is not None
    assert res_l2_priv.error.error == "INSUFFICIENT_ROLE"

    # 4. L3 caller with NO privileges (production_write=False, attachment_access=False) -> Allowed!
    token_l3 = _create_sec_jwt(
        sub="USR-L3", role="L3", production_write=False, attachment_access=False
    )
    res_l3 = await service.handle_tool_call(
        tool_name="investigate_incident",
        arguments={"initial_hypothesis": "Test incident"},
        authorization_header=f"Bearer {token_l3}",
    )
    assert res_l3.success is True
    assert isinstance(res_l3.result, dict)


def test_investigation_dispatch_headers_minimal() -> None:
    """Verify Gateway -> Investigation MCP dispatches ONLY transport Accept, zero custom headers."""

    settings = GatewaySettings()
    registry = GatewayBackendRegistry(settings=settings)
    dispatcher = HttpToolDispatcher(backend_registry=registry)

    req = GatewayDispatchRequest(
        tool_name="investigate_incident",
        arguments={"initial_hypothesis": "Test"},
        security_context=SecurityContext(
            principal=PrincipalIdentity(user_id="USR-SECRET-99", role="L3"),
            token_id="tok-sec-99",
            attributes={"production_write": True, "attachment_access": True},
        ),
        correlation_id="corr-test-1234",
    )

    headers = dispatcher._build_trusted_headers(req, TargetServer.INVESTIGATION)

    # 1. Accept must be present
    assert headers.get("Accept") == "application/json, text/event-stream"

    # 2. All 5 internal custom headers must be absent
    assert INTERNAL_HEADER_CORRELATION_ID not in headers
    assert INTERNAL_HEADER_USER_ID not in headers
    assert INTERNAL_HEADER_USER_ROLE not in headers
    assert INTERNAL_HEADER_PRODUCTION_WRITE not in headers
    assert INTERNAL_HEADER_ATTACHMENT_ACCESS not in headers

    # 3. Raw Authorization must be absent
    assert "Authorization" not in headers
    assert "authorization" not in headers
    assert len(headers) == 1


def test_existing_backend_dispatch_headers_preserved() -> None:
    """Verify Gateway -> SuperOffice and Diagnostics MCP preserve all 5 internal headers."""

    settings = GatewaySettings()
    registry = GatewayBackendRegistry(settings=settings)
    dispatcher = HttpToolDispatcher(backend_registry=registry)

    req = GatewayDispatchRequest(
        tool_name="get_ticket",
        arguments={"ticket_id": 10},
        security_context=SecurityContext(
            principal=PrincipalIdentity(user_id="USR-L1-42", role="L1"),
            token_id="tok-l1-42",
            attributes={"production_write": False, "attachment_access": False},
        ),
        correlation_id="corr-so-777",
    )

    for target in (
        TargetServer.SUPEROFFICE,
        TargetServer.DIAGNOSTICS,
        TargetServer.KNOWLEDGE,
        TargetServer.INFRASTRUCTURE,
    ):
        headers = dispatcher._build_trusted_headers(req, target)
        assert headers.get("Accept") == "application/json, text/event-stream"
        assert headers.get(INTERNAL_HEADER_CORRELATION_ID) == "corr-so-777"
        assert headers.get(INTERNAL_HEADER_USER_ID) == "USR-L1-42"
        assert headers.get(INTERNAL_HEADER_USER_ROLE) == "L1"
        assert headers.get(INTERNAL_HEADER_PRODUCTION_WRITE) == "false"
        assert headers.get(INTERNAL_HEADER_ATTACHMENT_ACCESS) == "false"
        assert "Authorization" not in headers


def test_sanitizer_typed_schema_compatibility() -> None:
    """Verify RecursiveOutputSanitizer scrubs sensitive strings without violating response DTO."""

    sanitizer = RecursiveOutputSanitizer()

    # Payload with valid observations and an embedded email and API key inside an error message
    raw_payload = {
        "source_outcomes": [
            {
                "source": "superoffice_crm",
                "status": "SUCCESS",
                "error_code": None,
                "error_message": None,
            },
            {
                "source": "application_logs",
                "status": "FAILED",
                "error_code": "SOURCE_EXECUTION_FAILED",
                "error_message": (
                    "Incident reported by admin.user@superoffice.com with key "
                    "sk_1234567890abcdef1234"
                ),
            },
        ],
        "evidence": [
            {
                "source": "superoffice_crm",
                "timestamp": "2026-09-03T09:00:00Z",
                "data": {
                    "observation_type": "ticket",
                    "ticket_id": 42,
                    "status": "Open",
                    "category": "Database",
                    "priority": "High",
                },
            },
            {
                "source": "mssql_diagnostics",
                "timestamp": "2026-09-03T09:01:00Z",
                "data": {
                    "observation_type": "database_health",
                    "is_healthy": True,
                    "active_connections": 25,
                    "latency_ms": 4.5,
                },
            },
        ],
    }

    sanitized = sanitizer.sanitize(raw_payload)
    assert isinstance(sanitized, dict)

    # 1. Verify secrets/PII were scrubbed
    failed_outcome = sanitized["source_outcomes"][1]
    msg = failed_outcome["error_message"]
    assert "admin.user@superoffice.com" not in msg
    assert "[REDACTED_EMAIL]" in msg
    assert "sk_1234567890abcdef1234" not in msg
    assert "[REDACTED_API_KEY]" in msg

    # 2. Verify structural validity passes Pydantic model validation with 100% fidelity
    validated = InvestigateIncidentResponseDTO.model_validate(sanitized)
    assert validated.source_outcomes[0].status == "SUCCESS"
    assert validated.source_outcomes[1].status == "FAILED"
    assert len(validated.evidence) == 2
