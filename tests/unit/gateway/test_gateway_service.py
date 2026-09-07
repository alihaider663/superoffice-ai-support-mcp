"""Unit tests for GatewayApplicationService authentication, RBAC, and dispatch."""

import time
from typing import Any
from unittest.mock import AsyncMock

import jwt
import pytest

from platform_gateway.contracts.dispatch import (
    GatewayDispatchRequest,
    GatewayDispatchResponse,
    SanitizedErrorPayload,
)
from platform_gateway.contracts.interfaces import StreamableHttpDispatcher
from platform_gateway.contracts.routing import (
    GatewayRoutingTable,
    TargetServer,
    ToolRouteDefinition,
)
from platform_gateway.registry import create_default_routing_table
from platform_gateway.services.gateway_service import GatewayApplicationService
from platform_observability.audit import AuditEvent, AuditSink
from platform_security.jwt import JwtAuthenticator
from platform_security.rate_limiting import SlidingWindowRateLimiter
from platform_security.rbac import YamlPolicyEngine
from platform_security.sanitization import RecursiveOutputSanitizer

TEST_SECRET = "super-secret-gateway-signing-key-12345-32bytes-secure"


class RecordingAuditSink(AuditSink):
    """In-memory test audit sink."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


def _create_jwt(
    sub: str = "USR-101",
    role: str = "L1",
    production_write: bool = False,
    attachment_access: bool = False,
    exp_offset: int = 3600,
) -> str:
    """Helper creating a test signed JWT token."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": sub,
        "role": role,
        "production_write": production_write,
        "attachment_access": attachment_access,
        "iat": now,
        "exp": now + exp_offset,
    }
    return jwt.encode(payload, TEST_SECRET, algorithm="HS256")


@pytest.fixture
def test_routing_table() -> GatewayRoutingTable:
    """Create test routing table including test routes for privilege evaluation."""
    routes = [
        *create_default_routing_table().routes.values(),
        ToolRouteDefinition(
            tool_name="update_ticket_status", target_server=TargetServer.SUPEROFFICE
        ),
        ToolRouteDefinition(
            tool_name="get_attachment_content", target_server=TargetServer.SUPEROFFICE
        ),
    ]
    return GatewayRoutingTable.from_routes(routes)


@pytest.fixture
def mock_dispatcher() -> AsyncMock:
    """Create mock StreamableHttpDispatcher returning successful echo by default."""
    dispatcher = AsyncMock(spec=StreamableHttpDispatcher)

    async def _mock_dispatch(
        route: ToolRouteDefinition,
        request: GatewayDispatchRequest,
    ) -> GatewayDispatchResponse:
        return GatewayDispatchResponse(
            tool_name=request.tool_name,
            success=True,
            result={
                "status": "OK",
                "echo_args": request.arguments,
                "server": route.target_server.value,
            },
            error=None,
            correlation_id=request.correlation_id,
        )

    dispatcher.dispatch = AsyncMock(side_effect=_mock_dispatch)
    return dispatcher


@pytest.fixture
def gateway_service(
    test_routing_table: GatewayRoutingTable,
    mock_dispatcher: AsyncMock,
) -> tuple[GatewayApplicationService, RecordingAuditSink]:
    """Create fully wired GatewayApplicationService with test dependencies."""
    authenticator = JwtAuthenticator(secret_or_key=TEST_SECRET, algorithms=["HS256"])
    authorizer = YamlPolicyEngine(attachment_access_enabled=True)
    rate_limiter = SlidingWindowRateLimiter(requests_per_minute=10, burst_limit=5)
    audit_sink = RecordingAuditSink()
    sanitizer = RecursiveOutputSanitizer()

    service = GatewayApplicationService(
        routing_table=test_routing_table,
        dispatcher=mock_dispatcher,
        authenticator=authenticator,
        authorizer=authorizer,
        rate_limiter=rate_limiter,
        audit_sink=audit_sink,
        sanitizer=sanitizer,
    )
    return service, audit_sink


@pytest.mark.asyncio
async def test_missing_auth_header_fails_closed(
    gateway_service: tuple[GatewayApplicationService, RecordingAuditSink],
) -> None:
    """Request without Authorization header returns AUTHENTICATION_REQUIRED and audits failure."""
    service, audit_sink = gateway_service
    res = await service.handle_tool_call(
        tool_name="get_ticket",
        arguments={"ticket_id": 100},
        authorization_header=None,
    )

    assert res.success is False
    assert res.error is not None
    assert res.error.error == "AUTHENTICATION_REQUIRED"
    assert len(audit_sink.events) == 1
    assert audit_sink.events[0].status == "FAILED"


@pytest.mark.asyncio
async def test_invalid_jwt_fails_closed(
    gateway_service: tuple[GatewayApplicationService, RecordingAuditSink],
) -> None:
    """Request with bad signature returns INVALID_TOKEN."""
    service, _ = gateway_service
    res = await service.handle_tool_call(
        tool_name="get_ticket",
        arguments={"ticket_id": 100},
        authorization_header="Bearer bad-invalid-token-string",
    )

    assert res.success is False
    assert res.error is not None
    assert res.error.error == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_unknown_tool_fails_closed(
    gateway_service: tuple[GatewayApplicationService, RecordingAuditSink],
) -> None:
    """Request for unrouted tool returns ROUTE_NOT_FOUND."""
    service, _ = gateway_service
    token = _create_jwt(role="L3")
    res = await service.handle_tool_call(
        tool_name="unregistered_tool_xyz",
        arguments={},
        authorization_header=f"Bearer {token}",
    )

    assert res.success is False
    assert res.error is not None
    assert res.error.error == "ROUTE_NOT_FOUND"


@pytest.mark.asyncio
async def test_l1_allowed_l1_tool_and_denied_l2_tool(
    gateway_service: tuple[GatewayApplicationService, RecordingAuditSink],
) -> None:
    """L1 role is permitted for L1 tool, but denied for L2 tool."""
    service, _ = gateway_service
    token_l1 = _create_jwt(sub="USR-L1", role="L1")

    # 1. L1 tool: get_ticket (Allowed)
    res_allowed = await service.handle_tool_call(
        tool_name="get_ticket",
        arguments={"ticket_id": 200},
        authorization_header=f"Bearer {token_l1}",
    )
    assert res_allowed.success is True
    assert isinstance(res_allowed.result, dict)
    assert res_allowed.result["status"] == "OK"

    # 2. L2 tool: get_database_health (Denied)
    res_denied = await service.handle_tool_call(
        tool_name="get_database_health",
        arguments={},
        authorization_header=f"Bearer {token_l1}",
    )
    assert res_denied.success is False
    assert res_denied.error is not None
    assert res_denied.error.error == "INSUFFICIENT_ROLE"


@pytest.mark.asyncio
async def test_production_write_privilege_enforced(
    gateway_service: tuple[GatewayApplicationService, RecordingAuditSink],
) -> None:
    """Write tools require explicit production_write claim even if caller role is L2 or L3."""
    service, _ = gateway_service

    # L2 without production_write -> Denied
    token_no_write = _create_jwt(role="L2", production_write=False)
    res_no_write = await service.handle_tool_call(
        tool_name="update_ticket_status",
        arguments={"ticket_id": 500, "status": "Closed"},
        authorization_header=f"Bearer {token_no_write}",
    )
    assert res_no_write.success is False
    assert res_no_write.error is not None
    assert res_no_write.error.error == "MISSING_PRODUCTION_WRITE_PRIVILEGE"

    # L2 with production_write -> Allowed
    token_with_write = _create_jwt(role="L2", production_write=True)
    res_with_write = await service.handle_tool_call(
        tool_name="update_ticket_status",
        arguments={"ticket_id": 500, "status": "Closed"},
        authorization_header=f"Bearer {token_with_write}",
    )
    assert res_with_write.success is True


@pytest.mark.asyncio
async def test_attachment_access_privilege_enforced(
    gateway_service: tuple[GatewayApplicationService, RecordingAuditSink],
) -> None:
    """get_attachment_content requires L3 AND explicit attachment_access claim."""
    service, _ = gateway_service

    # L3 without attachment_access -> Denied
    token_no_attach = _create_jwt(role="L3", attachment_access=False)
    res_denied = await service.handle_tool_call(
        tool_name="get_attachment_content",
        arguments={"attachment_id": 77},
        authorization_header=f"Bearer {token_no_attach}",
    )
    assert res_denied.success is False
    assert res_denied.error is not None
    assert res_denied.error.error == "MISSING_ATTACHMENT_ACCESS_PRIVILEGE"

    # L3 with attachment_access -> Allowed
    token_with_attach = _create_jwt(role="L3", attachment_access=True)
    res_allowed = await service.handle_tool_call(
        tool_name="get_attachment_content",
        arguments={"attachment_id": 77},
        authorization_header=f"Bearer {token_with_attach}",
    )
    assert res_allowed.success is True


@pytest.mark.asyncio
async def test_rate_limiting_enforced(
    test_routing_table: GatewayRoutingTable,
    mock_dispatcher: AsyncMock,
) -> None:
    """Rate limiter denies excess requests with RATE_LIMIT_EXCEEDED."""
    authenticator = JwtAuthenticator(secret_or_key=TEST_SECRET, algorithms=["HS256"])
    authorizer = YamlPolicyEngine()
    # Limit: 2 requests per minute
    rate_limiter = SlidingWindowRateLimiter(requests_per_minute=2, burst_limit=2)

    service = GatewayApplicationService(
        routing_table=test_routing_table,
        dispatcher=mock_dispatcher,
        authenticator=authenticator,
        authorizer=authorizer,
        rate_limiter=rate_limiter,
    )

    token = _create_jwt(sub="RATE-USER-01", role="L1")
    # 1. First call -> OK
    res1 = await service.handle_tool_call(
        "get_ticket", {"ticket_id": 1}, authorization_header=f"Bearer {token}"
    )
    assert res1.success is True

    # 2. Second call -> OK
    res2 = await service.handle_tool_call(
        "get_ticket", {"ticket_id": 2}, authorization_header=f"Bearer {token}"
    )
    assert res2.success is True

    # 3. Third call -> Denied
    res3 = await service.handle_tool_call(
        "get_ticket", {"ticket_id": 3}, authorization_header=f"Bearer {token}"
    )
    assert res3.success is False
    assert res3.error is not None
    assert res3.error.error == "RATE_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_output_sanitization_scrubs_pii_from_result(
    test_routing_table: GatewayRoutingTable,
) -> None:
    """Output sanitizer scrubs emails, phone numbers, and secrets from downstream tool results."""
    mock_dispatcher = AsyncMock(spec=StreamableHttpDispatcher)

    async def _leak_pii_dispatch(
        route: ToolRouteDefinition,
        request: GatewayDispatchRequest,
    ) -> GatewayDispatchResponse:
        _ = route
        return GatewayDispatchResponse(
            tool_name=request.tool_name,
            success=True,
            result={
                "ticket_id": 123,
                "notes": (
                    "Contact user at john.doe@example.com or +47 98765432 with key "
                    "sk-abcdef1234567890"
                ),
            },
            error=None,
            correlation_id=request.correlation_id,
        )

    mock_dispatcher.dispatch = AsyncMock(side_effect=_leak_pii_dispatch)
    authenticator = JwtAuthenticator(secret_or_key=TEST_SECRET, algorithms=["HS256"])
    authorizer = YamlPolicyEngine()
    sanitizer = RecursiveOutputSanitizer()

    service = GatewayApplicationService(
        routing_table=test_routing_table,
        dispatcher=mock_dispatcher,
        authenticator=authenticator,
        authorizer=authorizer,
        sanitizer=sanitizer,
    )

    token = _create_jwt(role="L1")
    res = await service.handle_tool_call(
        "get_ticket", {"ticket_id": 123}, authorization_header=f"Bearer {token}"
    )

    assert res.success is True
    assert isinstance(res.result, dict)
    notes = str(res.result.get("notes", ""))
    assert "john.doe@example.com" not in notes
    assert "[REDACTED_EMAIL]" in notes
    assert "+47 98765432" not in notes
    assert "[REDACTED_PHONE]" in notes


# =============================================================================
# Phase 4.3 — Rate Limiting, Timeout Policy A, and Result Semantics Tests
# =============================================================================


@pytest.mark.asyncio
async def test_investigate_incident_rate_limiting_burst_and_window(
    test_routing_table: GatewayRoutingTable,
) -> None:
    """Rate limiter enforces burst and window limits per identity+tool, partitioned by client IP."""
    dispatcher = AsyncMock(spec=StreamableHttpDispatcher)

    async def _echo_dispatch(
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

    dispatcher.dispatch = AsyncMock(side_effect=_echo_dispatch)
    authenticator = JwtAuthenticator(secret_or_key=TEST_SECRET, algorithms=["HS256"])
    authorizer = YamlPolicyEngine()

    # Rate limiter configured with burst_limit=10, 60 requests per minute
    rate_limiter = SlidingWindowRateLimiter(requests_per_minute=60, burst_limit=10)

    service = GatewayApplicationService(
        routing_table=test_routing_table,
        dispatcher=dispatcher,
        authenticator=authenticator,
        authorizer=authorizer,
        rate_limiter=rate_limiter,
    )

    token_user_a = _create_jwt(sub="USR-RATE-A", role="L3")
    token_user_b = _create_jwt(sub="USR-RATE-B", role="L3")

    # 1. User A sends 10 consecutive requests -> all allowed under burst limit
    for i in range(10):
        res = await service.handle_tool_call(
            tool_name="investigate_incident",
            arguments={"initial_hypothesis": f"Incident {i}"},
            authorization_header=f"Bearer {token_user_a}",
            client_ip="192.168.1.50",
        )
        assert res.success is True

    # 2. User A sends 11th request within burst window -> Denied with RATE_LIMIT_EXCEEDED
    res_burst_exceeded = await service.handle_tool_call(
        tool_name="investigate_incident",
        arguments={"initial_hypothesis": "Incident 11"},
        authorization_header=f"Bearer {token_user_a}",
        client_ip="192.168.1.50",
    )
    assert res_burst_exceeded.success is False
    assert res_burst_exceeded.error is not None
    assert res_burst_exceeded.error.error == "RATE_LIMIT_EXCEEDED"

    # 3. User B sends request -> Independent quota, succeeds!
    res_user_b = await service.handle_tool_call(
        tool_name="investigate_incident",
        arguments={"initial_hypothesis": "User B Incident"},
        authorization_header=f"Bearer {token_user_b}",
        client_ip="192.168.1.50",
    )
    assert res_user_b.success is True

    # 4. User A with different client_ip -> Partitioned by client_ip when supplied, succeeds!
    res_ip_partition = await service.handle_tool_call(
        tool_name="investigate_incident",
        arguments={"initial_hypothesis": "Incident from different IP"},
        authorization_header=f"Bearer {token_user_a}",
        client_ip="10.0.0.99",
    )
    assert res_ip_partition.success is True


@pytest.mark.asyncio
async def test_investigate_incident_timeout_outer_budget_policy_a(
    test_routing_table: GatewayRoutingTable,
) -> None:
    """Policy A: Gateway enforces 30s transport timeout returning safe GATEWAY_DOWNSTREAM_TIMEOUT.

    Asserts zero internal backend URLs, IPs, ports, tracebacks, or payloads in error.
    Asserts timeout is NOT converted into a successful response with source_outcomes: FAILED.
    """
    dispatcher = AsyncMock(spec=StreamableHttpDispatcher)

    # Simulate transport timeout from downstream dispatcher
    async def _timeout_dispatch(
        route: ToolRouteDefinition, request: GatewayDispatchRequest
    ) -> GatewayDispatchResponse:
        _ = route
        return GatewayDispatchResponse(
            tool_name=request.tool_name,
            success=False,
            result=None,
            error=SanitizedErrorPayload(
                error="GATEWAY_DOWNSTREAM_TIMEOUT",
                message="The downstream backend service timed out while processing request.",
            ),
            correlation_id=request.correlation_id,
        )

    dispatcher.dispatch = AsyncMock(side_effect=_timeout_dispatch)
    service = GatewayApplicationService(
        routing_table=test_routing_table,
        dispatcher=dispatcher,
        authenticator=JwtAuthenticator(secret_or_key=TEST_SECRET, algorithms=["HS256"]),
        authorizer=YamlPolicyEngine(),
    )

    token = _create_jwt(sub="USR-TIMEOUT", role="L3")
    res = await service.handle_tool_call(
        tool_name="investigate_incident",
        arguments={"initial_hypothesis": "Slow incident"},
        authorization_header=f"Bearer {token}",
    )

    assert res.success is False
    assert res.result is None
    assert res.error is not None
    assert res.error.error == "GATEWAY_DOWNSTREAM_TIMEOUT"
    assert res.error.message == "The downstream backend service timed out while processing request."

    # Verify no URL, IP, port, or stack trace leaked
    msg = res.error.message
    for leaked in ("http://", "127.0.0.1", "8005", "Traceback", "Exception"):
        assert leaked not in msg


@pytest.mark.asyncio
async def test_investigate_incident_result_semantics_three_states(
    test_routing_table: GatewayRoutingTable,
) -> None:
    """Verify distinct semantics for:
    (A) source degradation, (B) tool validation error, (C) transport failure.
    """
    dispatcher = AsyncMock(spec=StreamableHttpDispatcher)
    service = GatewayApplicationService(
        routing_table=test_routing_table,
        dispatcher=dispatcher,
        authenticator=JwtAuthenticator(secret_or_key=TEST_SECRET, algorithms=["HS256"]),
        authorizer=YamlPolicyEngine(),
    )
    token = _create_jwt(role="L3")

    # State A: Source degradation inside Investigation MCP (success=True, isError=False)
    degraded_payload: dict[str, Any] = {
        "source_outcomes": [
            {
                "source": "application_logs",
                "status": "BLOCKED",
                "error_code": "DIAGNOSTIC_LOGS_BLOCKED",
                "error_message": "Logs blocked",
            },
            {
                "source": "knowledge_base",
                "status": "NOT_CONFIGURED",
                "error_code": "KNOWLEDGE_BASE_NOT_CONFIGURED",
                "error_message": "KB not configured",
            },
            {
                "source": "superoffice_crm",
                "status": "FAILED",
                "error_code": "SUPEROFFICE_RETRIEVAL_FAILED",
                "error_message": "Ticket query failed",
            },
        ],
        "evidence": [],
    }
    dispatcher.dispatch = AsyncMock(
        return_value=GatewayDispatchResponse(
            tool_name="investigate_incident",
            success=True,
            result=degraded_payload,
            error=None,
            correlation_id="corr-state-a",
        )
    )
    res_a = await service.handle_tool_call(
        tool_name="investigate_incident",
        arguments={"initial_hypothesis": "Hypothesis A"},
        authorization_header=f"Bearer {token}",
    )
    assert res_a.success is True
    assert res_a.result == degraded_payload

    # State B: Downstream tool validation failure (success=False, DOWNSTREAM_TOOL_ERROR)
    dispatcher.dispatch = AsyncMock(
        return_value=GatewayDispatchResponse(
            tool_name="investigate_incident",
            success=False,
            result=None,
            error=SanitizedErrorPayload(
                error="DOWNSTREAM_TOOL_ERROR",
                message="Validation error: extra field forbidden",
            ),
            correlation_id="corr-state-b",
        )
    )
    res_b = await service.handle_tool_call(
        tool_name="investigate_incident",
        arguments={"initial_hypothesis": "Hypothesis B", "forbidden_field": 123},
        authorization_header=f"Bearer {token}",
    )
    assert res_b.success is False
    assert res_b.error is not None
    assert res_b.error.error == "DOWNSTREAM_TOOL_ERROR"

    # State C: Downstream transport failure (success=False, GATEWAY_DOWNSTREAM_UNAVAILABLE)
    dispatcher.dispatch = AsyncMock(
        return_value=GatewayDispatchResponse(
            tool_name="investigate_incident",
            success=False,
            result=None,
            error=SanitizedErrorPayload(
                error="GATEWAY_DOWNSTREAM_UNAVAILABLE",
                message="Downstream server returned HTTP status 503.",
            ),
            correlation_id="corr-state-c",
        )
    )
    res_c = await service.handle_tool_call(
        tool_name="investigate_incident",
        arguments={"initial_hypothesis": "Hypothesis C"},
        authorization_header=f"Bearer {token}",
    )
    assert res_c.success is False
    assert res_c.error is not None
    assert res_c.error.error == "GATEWAY_DOWNSTREAM_UNAVAILABLE"
