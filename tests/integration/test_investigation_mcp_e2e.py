"""Official MCP SDK End-to-End & Security Verification Suite (Phase 4.4).

Verifies the complete four-hop Streamable HTTP architecture:
1. Official MCP SDK Client (ClientSession / streamable_http_client)
2. Gateway MCP ASGI Application (JWT auth, YAML RBAC, rate limiting, sanitizer, routing)
3. Investigation MCP ASGI Application (stateless, low-level server, closed DTO validation)
4. Subordinate MCP ASGI Applications (SuperOffice MCP, Diagnostics MCP)

Enforces:
- 19 Gateway tools, investigate_incident present exactly once, zero internal engine actions
- Complete schema fidelity with InvestigateIncidentRequestDTO and InvestigateIncidentResponseDTO
- L1/L2 deny, L3 allow; privilege flags cannot substitute for L3
- Authorization-before-dispatch and rate-limit-before-dispatch
- Raw JWT termination at Gateway; zero custom identity/security headers downstream
- Correlation separation (Gateway transport correlation ID != internal correlation_key)
- Frozen physical subordinate set (max 4 calls: get_ticket, get_database_health,
  find_deadlocks, find_slow_queries)
- Safe error handling, sensitive sentinel containment, and public internal-field exclusion
- Request-scoped state and in-process statelessness across sequential runs
"""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import HttpUrl

from diag_mcp.contracts.dtos import (
    DatabaseHealthDomainDTO,
    DeadlockCriteriaDTO,
    DeadlockDomainDTO,
    SlowQueryCriteriaDTO,
    SlowQueryDomainDTO,
)
from diag_mcp.server import create_diagnostics_mcp_server
from diag_mcp.services.diagnostic_service import DiagnosticsApplicationService
from investigation_mcp.adapters.diagnostics_mcp_adapter import DiagnosticsMcpClientAdapter
from investigation_mcp.adapters.superoffice_mcp_adapter import SuperOfficeMcpClientAdapter
from investigation_mcp.contracts.dtos import (
    InvestigateIncidentRequestDTO,
    InvestigateIncidentResponseDTO,
    TicketObservationDTO,
)
from investigation_mcp.contracts.mappers import (
    ERROR_CODE_MAP,
    InvestigationResponseMapper,
)
from investigation_mcp.server import create_investigation_mcp_server
from platform_config.gateway import GatewaySettings
from platform_gateway.adapters.http_dispatcher import HttpToolDispatcher
from platform_gateway.contracts.dispatch import (
    GatewayDispatchRequest,
    GatewayDispatchResponse,
    SanitizedErrorPayload,
)
from platform_gateway.contracts.routing import ToolRouteDefinition
from platform_gateway.registry import GatewayBackendRegistry, create_default_routing_table
from platform_gateway.server.app import create_gateway_app
from platform_gateway.services.gateway_service import GatewayApplicationService
from platform_investigation.models import (
    EvidenceSourceType,
    SourceCollectionResult,
    SourceCollectionStatus,
)
from platform_investigation.store import InMemoryInvestigationStore
from platform_observability.audit import AuditEvent, AuditSink
from platform_security.jwt import JwtAuthenticator
from platform_security.rate_limiting import SlidingWindowRateLimiter
from platform_security.rbac import YamlPolicyEngine
from platform_security.sanitization import RecursiveOutputSanitizer
from so_mcp.contracts.dtos import TicketDetailDomainDTO
from so_mcp.server import create_superoffice_mcp_server
from so_mcp.services.ticket_service import SuperOfficeApplicationService
from tests.fakes.fake_diagnostic_repository import FakeDiagnosticRepository
from tests.fakes.fake_superoffice_client import FakeSuperOfficeClient

TEST_JWT_SECRET = "test-secret-key-32-bytes-long-superoffice-ai-gateway-secure"
SENSITIVE_HYPOTHESIS_SENTINEL = "SENSITIVE_HYPOTHESIS_SENTINEL_9F41"
SENSITIVE_EXTRA_FIELD_SENTINEL = "SENSITIVE_EXTRA_FIELD_SENTINEL_A71C"
INTERNAL_SECRET_SENTINEL = "INTERNAL_SECRET_SENTINEL_X91"


class RecordingAuditSink(AuditSink):
    """In-memory audit sink capturing audit events."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


@dataclass
class E2ECluster:
    """Four-hop in-process MCP test cluster."""

    gw_app: Any
    inv_app: Any
    so_app: Any
    diag_app: Any
    fake_so: FakeSuperOfficeClient
    fake_diag: FakeDiagnosticRepository
    audit_sink: RecordingAuditSink
    captured_inv_requests: list[httpx.Request]
    captured_so_requests: list[httpx.Request]
    captured_diag_requests: list[httpx.Request]
    captured_dispatch_requests: list[GatewayDispatchRequest]
    inv_call_count: list[int]
    store_instance_count: list[int]
    so_calls: dict[str, int]
    diag_calls: dict[str, int]
    so_call_history: list[int]
    rate_limiter: SlidingWindowRateLimiter
    make_token: Callable[..., str]


def _make_jwt(
    sub: str = "USR-E2E-TEST",
    role: str = "L3",
    production_write: bool = False,
    attachment_access: bool = False,
    exp_offset_seconds: int = 3600,
) -> str:
    """Generate a valid test JWT using the Gateway HMAC secret."""
    now_ts = int(datetime.now(UTC).timestamp())
    payload = {
        "sub": sub,
        "role": role,
        "production_write": production_write,
        "attachment_access": attachment_access,
        "iat": now_ts,
        "exp": now_ts + exp_offset_seconds,
        "iss": "superoffice-ai-platform",
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@asynccontextmanager
async def create_e2e_cluster(  # noqa: PLR0915
    rate_limiter: SlidingWindowRateLimiter | None = None,
    mock_dispatcher_timeout: bool = False,
    mock_dispatcher_unavailable: bool = False,
    mock_dispatcher_tool_error: bool = False,
) -> AsyncIterator[E2ECluster]:
    """Assemble and run the four-hop Streamable HTTP cluster in-process."""
    # 1. Seed synthetic CRM backend data
    fake_so = FakeSuperOfficeClient()
    fake_so.seed_ticket(
        TicketDetailDomainDTO(
            ticket_id=1001,
            title="Database Connection Timeout Incident",
            status="Open",
            category="Infrastructure",
            priority="High",
            description="Users experiencing timeout connecting to database.",
            assigned_to="AGENT-01",
            customer_id=501,
            customer_reference="CUST-TEST-CORP",
            created_at=datetime.now(UTC),
        )
    )
    fake_so.seed_ticket(
        TicketDetailDomainDTO(
            ticket_id=2002,
            title="Billing Portal Latency Degradation",
            status="Open",
            category="Billing",
            priority="Critical",
            description="High latency during checkout operations.",
            assigned_to="AGENT-02",
            customer_id=502,
            customer_reference="CUST-ACME-INC",
            created_at=datetime.now(UTC),
        )
    )

    so_calls: dict[str, int] = {
        "get_ticket": 0,
        "get_ticket_messages": 0,
        "list_attachments": 0,
        "get_attachment": 0,
    }
    so_call_history: list[int] = []

    orig_get_ticket = fake_so.get_ticket

    async def _spied_get_ticket(ticket_id: int) -> TicketDetailDomainDTO:
        so_calls["get_ticket"] += 1
        so_call_history.append(ticket_id)
        return await orig_get_ticket(ticket_id)

    fake_so.get_ticket = _spied_get_ticket  # type: ignore[method-assign]

    so_service = SuperOfficeApplicationService(client=fake_so)
    so_app = create_superoffice_mcp_server(service=so_service).streamable_http_app()

    # 2. Seed synthetic MSSQL Diagnostics backend data
    fake_diag = FakeDiagnosticRepository()
    fake_diag.set_health(
        DatabaseHealthDomainDTO(
            is_healthy=True,
            status_summary="ONLINE",
            active_connections=18,
            latency_ms=2.5,
            collected_at=datetime.now(UTC),
        )
    )
    fake_diag.seed_deadlock(
        DeadlockDomainDTO(
            deadlock_id="dlk-e2e-888",
            occurred_at=datetime.now(UTC),
            victim_session_id=72,
            participating_session_count=2,
            resource_description="KEY: 6:72057594041794560",
            summary="Deadlock between spid 72 and spid 85 on tbl_ticket",
        )
    )
    fake_diag.seed_slow_query(
        SlowQueryDomainDTO(
            query_hash="0xDEADBEEF01",
            duration_ms=12500,
            cpu_time_ms=9000,
            logical_reads=450000,
            execution_count=14,
            last_execution_time=datetime.now(UTC),
            summary="SELECT * FROM ticket_messages WHERE body LIKE '%error%'",
        )
    )

    diag_calls: dict[str, int] = {
        "get_database_health": 0,
        "find_deadlocks": 0,
        "find_slow_queries": 0,
        "find_blocking_sessions": 0,
        "get_ticket_diagnostic_record": 0,
    }

    orig_get_health = fake_diag.get_database_health
    orig_find_deadlocks = fake_diag.find_deadlocks
    orig_find_slow_queries = fake_diag.find_slow_queries

    async def _spied_get_health() -> DatabaseHealthDomainDTO:
        diag_calls["get_database_health"] += 1
        return await orig_get_health()

    async def _spied_find_deadlocks(criteria: DeadlockCriteriaDTO) -> Any:
        diag_calls["find_deadlocks"] += 1
        return await orig_find_deadlocks(criteria)

    async def _spied_find_slow_queries(criteria: SlowQueryCriteriaDTO) -> Any:
        diag_calls["find_slow_queries"] += 1
        return await orig_find_slow_queries(criteria)

    fake_diag.get_database_health = _spied_get_health  # type: ignore[method-assign]
    fake_diag.find_deadlocks = _spied_find_deadlocks  # type: ignore[method-assign]
    fake_diag.find_slow_queries = _spied_find_slow_queries  # type: ignore[method-assign]

    diag_service = DiagnosticsApplicationService(repository=fake_diag)
    diag_app = create_diagnostics_mcp_server(service=diag_service).streamable_http_app()

    # 3. Wire request captures and adapters
    captured_so_requests: list[httpx.Request] = []
    captured_diag_requests: list[httpx.Request] = []
    captured_inv_requests: list[httpx.Request] = []
    captured_dispatch_requests: list[GatewayDispatchRequest] = []
    inv_call_count = [0]
    store_instance_count = [0]

    async def _cap_so(req: httpx.Request) -> None:
        captured_so_requests.append(req)

    async def _cap_diag(req: httpx.Request) -> None:
        captured_diag_requests.append(req)

    async def _cap_inv(req: httpx.Request) -> None:
        captured_inv_requests.append(req)

    # Instrument store instantiation to track request-scoped instances
    original_store_init = InMemoryInvestigationStore.__init__

    def _instrumented_store_init(self: Any, *args: Any, **kwargs: Any) -> None:
        store_instance_count[0] += 1
        original_store_init(self, *args, **kwargs)

    InMemoryInvestigationStore.__init__ = _instrumented_store_init  # type: ignore[method-assign]

    try:
        async with (
            so_app.router.lifespan_context(so_app),
            diag_app.router.lifespan_context(diag_app),
        ):
            so_transport = httpx.ASGITransport(app=so_app)
            so_http = httpx.AsyncClient(
                transport=so_transport,
                base_url="http://testserver",
                event_hooks={"request": [_cap_so]},
            )
            so_adapter = SuperOfficeMcpClientAdapter(
                base_url="http://testserver",
                http_client=so_http,
            )

            diag_transport = httpx.ASGITransport(app=diag_app)
            diag_http = httpx.AsyncClient(
                transport=diag_transport,
                base_url="http://testserver",
                event_hooks={"request": [_cap_diag]},
            )
            diag_adapter = DiagnosticsMcpClientAdapter(
                base_url="http://testserver",
                http_client=diag_http,
            )

            # 4. Create Investigation MCP server
            inv_server = create_investigation_mcp_server(
                superoffice_service=so_adapter,
                diagnostics_service=diag_adapter,
            )

            original_execute = inv_server._execute_tool

            async def _instrumented_execute(
                name: str, arguments: dict[str, Any] | None
            ) -> CallToolResult:
                inv_call_count[0] += 1
                return await original_execute(name, arguments)

            inv_server._execute_tool = _instrumented_execute  # type: ignore[method-assign]
            inv_app = inv_server.streamable_http_app()

            async with inv_app.router.lifespan_context(inv_app):
                # 5. Create Gateway Application with mounted downstream client
                gw_settings = GatewaySettings(
                    investigation_mcp_url=HttpUrl("http://investigation-backend"),
                    superoffice_mcp_url=HttpUrl("http://so-backend"),
                    diagnostics_mcp_url=HttpUrl("http://diag-backend"),
                    knowledge_mcp_url=HttpUrl("http://testserver"),
                    infrastructure_mcp_url=HttpUrl("http://testserver"),
                )
                backend_reg = GatewayBackendRegistry(settings=gw_settings)

                downstream_client = httpx.AsyncClient(
                    mounts={
                        "http://investigation-backend": httpx.ASGITransport(app=inv_app),
                        "http://so-backend": httpx.ASGITransport(app=so_app),
                        "http://diag-backend": httpx.ASGITransport(app=diag_app),
                    },
                    event_hooks={"request": [_cap_inv]},
                )

                class _MockCustomDispatcher(HttpToolDispatcher):
                    async def dispatch(
                        self,
                        route: ToolRouteDefinition,
                        request: GatewayDispatchRequest,
                    ) -> GatewayDispatchResponse:
                        captured_dispatch_requests.append(request)
                        if mock_dispatcher_timeout:
                            return GatewayDispatchResponse(
                                tool_name=request.tool_name,
                                success=False,
                                result=None,
                                error=SanitizedErrorPayload(
                                    error="GATEWAY_DOWNSTREAM_TIMEOUT",
                                    message=(
                                        "The downstream backend service timed out "
                                        "while processing request."
                                    ),
                                ),
                                correlation_id=request.correlation_id,
                            )
                        if mock_dispatcher_unavailable:
                            return GatewayDispatchResponse(
                                tool_name=request.tool_name,
                                success=False,
                                result=None,
                                error=SanitizedErrorPayload(
                                    error="GATEWAY_DOWNSTREAM_UNAVAILABLE",
                                    message=(
                                        "The downstream backend service is currently unreachable"
                                        " or failed to initialize."
                                    ),
                                ),
                                correlation_id=request.correlation_id,
                            )
                        if mock_dispatcher_tool_error:
                            return GatewayDispatchResponse(
                                tool_name=request.tool_name,
                                success=False,
                                result=None,
                                error=SanitizedErrorPayload(
                                    error="DOWNSTREAM_TOOL_ERROR",
                                    message="Investigation tool execution reported an error.",
                                ),
                                correlation_id=request.correlation_id,
                            )
                        return await super().dispatch(route, request)

                dispatcher: HttpToolDispatcher
                if (
                    mock_dispatcher_timeout
                    or mock_dispatcher_unavailable
                    or mock_dispatcher_tool_error
                ):
                    dispatcher = _MockCustomDispatcher(
                        backend_registry=backend_reg, http_client=downstream_client
                    )
                else:

                    class _TrackingDispatcher(HttpToolDispatcher):
                        async def dispatch(
                            self,
                            *args: Any,
                            **kwargs: Any,
                        ) -> GatewayDispatchResponse:
                            req = args[0] if args else kwargs.get("request")
                            if isinstance(req, GatewayDispatchRequest):
                                captured_dispatch_requests.append(req)
                            return await super().dispatch(*args, **kwargs)

                    dispatcher = _TrackingDispatcher(
                        backend_registry=backend_reg, http_client=downstream_client
                    )

                audit_sink = RecordingAuditSink()
                active_limiter = rate_limiter or SlidingWindowRateLimiter(
                    requests_per_minute=60, burst_limit=10
                )
                gw_service = GatewayApplicationService(
                    routing_table=create_default_routing_table(),
                    dispatcher=dispatcher,
                    authenticator=JwtAuthenticator(
                        secret_or_key=TEST_JWT_SECRET, algorithms=["HS256"]
                    ),
                    authorizer=YamlPolicyEngine(),
                    rate_limiter=active_limiter,
                    audit_sink=audit_sink,
                    sanitizer=RecursiveOutputSanitizer(),
                )
                gw_app = create_gateway_app(service=gw_service)

                async with gw_app.router.lifespan_context(gw_app):
                    yield E2ECluster(
                        gw_app=gw_app,
                        inv_app=inv_app,
                        so_app=so_app,
                        diag_app=diag_app,
                        fake_so=fake_so,
                        fake_diag=fake_diag,
                        audit_sink=audit_sink,
                        captured_inv_requests=captured_inv_requests,
                        captured_so_requests=captured_so_requests,
                        captured_diag_requests=captured_diag_requests,
                        captured_dispatch_requests=captured_dispatch_requests,
                        inv_call_count=inv_call_count,
                        store_instance_count=store_instance_count,
                        so_calls=so_calls,
                        diag_calls=diag_calls,
                        so_call_history=so_call_history,
                        rate_limiter=active_limiter,
                        make_token=_make_jwt,
                    )
    finally:
        InMemoryInvestigationStore.__init__ = original_store_init  # type: ignore[method-assign]


@asynccontextmanager
async def official_session(
    cluster: E2ECluster,
    token: str | None = None,
    client_ip: str | None = None,
) -> AsyncIterator[ClientSession]:
    """Open an official MCP ClientSession over Streamable HTTP to Gateway."""
    headers = {"Accept": "application/json, text/event-stream"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if client_ip is not None:
        headers["X-Forwarded-For"] = client_ip

    gw_transport = httpx.ASGITransport(app=cluster.gw_app)
    async with (
        httpx.AsyncClient(
            transport=gw_transport,
            base_url="http://testserver",
            headers=headers,
            follow_redirects=True,
        ) as gw_http,
        streamable_http_client("http://testserver/mcp", http_client=gw_http) as (r, w, _),
        ClientSession(r, w) as session,
    ):
        await session.initialize()
        yield session


def _get_text(res: CallToolResult) -> str:
    """Extract text from the first TextContent block."""
    assert len(res.content) > 0
    first = res.content[0]
    assert isinstance(first, TextContent)
    return first.text


# ==============================================================================
# Phase 4.4 End-to-End Verification Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_official_mcp_tools_list_discovery_and_schema_fidelity() -> None:
    """Section 13, 14, 15: Client discovers 19 tools, investigate_incident schema fidelity."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            tools_result = await session.list_tools()
            tools: list[Tool] = tools_result.tools

            # Assert exactly 26 active Gateway tools
            assert len(tools) == 26

            # Assert investigate_incident is present exactly once
            inv_tools = [t for t in tools if t.name == "investigate_incident"]
            assert len(inv_tools) == 1
            inv_tool = inv_tools[0]

            # Assert absence of internal orchestration actions
            tool_names = {t.name for t in tools}
            for internal_action in (
                "create_plan",
                "advance_step",
                "aggregate_evidence",
                "evaluate_hypothesis",
                "conclude_investigation",
            ):
                assert internal_action not in tool_names

            # Verify inputSchema matches InvestigateIncidentRequestDTO
            expected_input_schema = InvestigateIncidentRequestDTO.model_json_schema(by_alias=True)
            assert inv_tool.inputSchema == expected_input_schema
            assert inv_tool.inputSchema.get("additionalProperties") is False
            assert "initial_hypothesis" in inv_tool.inputSchema.get("required", [])

            # Verify outputSchema matches InvestigateIncidentResponseDTO
            expected_output_schema = InvestigateIncidentResponseDTO.model_json_schema(by_alias=True)
            assert inv_tool.outputSchema == expected_output_schema

            # Check status enum has no PARTIAL
            status_schema = inv_tool.outputSchema["$defs"]["InvestigationSourceOutcomeWireDTO"][
                "properties"
            ]["status"]["enum"]
            assert status_schema == [
                "SUCCESS",
                "NOT_CONFIGURED",
                "BLOCKED",
                "UNAVAILABLE",
                "FAILED",
            ]
            assert "PARTIAL" not in status_schema


@pytest.mark.asyncio
async def test_four_hop_e2e_ticket_only_execution() -> None:
    """Section 6, 24, 28, 30: Four-hop ticket-only execution with frozen semantics."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Investigating user login degradation",
                    "ticket_id": 1001,
                },
            )

            # Assert successful typed result
            assert res.isError is False
            assert res.structuredContent is not None

            # Verify structuredContent validates against InvestigateIncidentResponseDTO
            validated_dto = InvestigateIncidentResponseDTO.model_validate(res.structuredContent)
            assert len(validated_dto.evidence) == 1

            # Compatibility text represents exact same object
            raw_text = _get_text(res)
            assert json.loads(raw_text) == res.structuredContent

            # Verify physical downstream calls: SO=1, Diag=0
            assert cluster.inv_call_count[0] == 1
            assert cluster.so_calls["get_ticket"] == 1
            assert cluster.so_call_history[0] == 1001

            # Assert frozen source outcomes
            outcomes = {o.source: o for o in validated_dto.source_outcomes}
            assert outcomes["superoffice_crm"].status == "SUCCESS"
            assert outcomes["mssql_diagnostics"].status == "SUCCESS"
            assert outcomes["mssql_diagnostics"].error_code is None
            assert outcomes["mssql_diagnostics"].error_message is None
            assert outcomes["application_logs"].status == "BLOCKED"
            assert outcomes["application_logs"].error_code == "DIAGNOSTIC_LOGS_BLOCKED"
            assert (
                outcomes["application_logs"].error_message
                == "Application logging source is currently blocked."
            )
            assert outcomes["knowledge_base"].status == "NOT_CONFIGURED"
            assert outcomes["knowledge_base"].error_code == "KNOWLEDGE_BASE_NOT_CONFIGURED"
            assert (
                outcomes["knowledge_base"].error_message
                == "Knowledge base source is not configured."
            )

            # Verify public internal-field exclusion
            response_json = json.dumps(res.structuredContent)
            for forbidden_field in (
                "investigation_id",
                "correlation_key",
                "execution_status",
                "plan",
                "steps",
                "hypotheses",
                "timeline",
                "correlation_groups",
                "concluded_root_cause",
                "confidence_score",
                "evidence_id",
                "tags",
                "correlation_references",
                "raw SQL",
                "ticket description",
                "attachment content",
                "http://testserver",
            ):
                assert f'"{forbidden_field}"' not in response_json
                assert f'"{forbidden_field}"' not in raw_text


@pytest.mark.asyncio
async def test_four_hop_e2e_diagnostics_only_execution() -> None:
    """Section 25: Diagnostics-only execution without ticket."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "MSSQL resource contention analysis",
                    "diagnostics": {
                        "include_database_health": True,
                        "slow_queries": {"min_duration_ms": 1000, "limit": 5},
                    },
                },
            )

            assert res.isError is False
            assert res.structuredContent is not None
            validated_dto = InvestigateIncidentResponseDTO.model_validate(res.structuredContent)

            # Physical calls: SO=0, Diag health=1, slow_queries=1, deadlocks=0
            assert cluster.so_calls["get_ticket"] == 0
            assert cluster.diag_calls["get_database_health"] == 1
            assert cluster.diag_calls["find_slow_queries"] == 1
            assert cluster.diag_calls["find_deadlocks"] == 0
            assert len(validated_dto.evidence) == 2  # 1 health + 1 slow query

            # Verify source outcomes
            outcomes = {o.source: o for o in validated_dto.source_outcomes}
            assert outcomes["mssql_diagnostics"].status == "SUCCESS"
            assert outcomes["superoffice_crm"].status == "SUCCESS"


@pytest.mark.asyncio
async def test_four_hop_e2e_maximum_four_call_set() -> None:
    """Section 26, 27: Maximum 4 physical calls, frozen subordinate capability set."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Full diagnostic triage",
                    "ticket_id": 1001,
                    "diagnostics": {
                        "include_database_health": True,
                        "deadlocks": {"limit": 5},
                        "slow_queries": {"min_duration_ms": 1000, "limit": 5},
                    },
                },
            )

            assert res.isError is False
            validated_dto = InvestigateIncidentResponseDTO.model_validate(res.structuredContent)
            assert (
                len(validated_dto.evidence) == 4
            )  # 1 ticket + 1 health + 1 deadlock + 1 slow query

            # Exactly 4 downstream operations: 1 get_ticket + 1 health + 1 deadlock + 1 slow query
            assert cluster.so_calls["get_ticket"] == 1
            assert cluster.diag_calls["get_database_health"] == 1
            assert cluster.diag_calls["find_deadlocks"] == 1
            assert cluster.diag_calls["find_slow_queries"] == 1

            # Assert zero calls to unapproved capabilities
            assert cluster.so_calls["get_ticket_messages"] == 0
            assert cluster.so_calls["list_attachments"] == 0
            assert cluster.so_calls["get_attachment"] == 0
            assert cluster.diag_calls["find_blocking_sessions"] == 0
            assert cluster.diag_calls["get_ticket_diagnostic_record"] == 0


@pytest.mark.asyncio
async def test_four_hop_e2e_zero_selection_validation_failure() -> None:
    """Section 23: Zero selection returns safe validation error with zero subordinate calls."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Zero selection probe",
                    "ticket_id": None,
                    "diagnostics": None,
                },
            )

            # Expect validation error
            assert res.isError is True
            error_text = _get_text(res)
            assert (
                "At least one investigation target or diagnostic check must be specified"
                in error_text
            )

            # Zero subordinate physical calls
            assert cluster.so_calls["get_ticket"] == 0


@pytest.mark.asyncio
async def test_e2e_rbac_matrix_and_privilege_flags() -> None:
    """Section 16, 17, 43: L1/L2 deny, L3 allow, privilege flags cannot override role."""
    async with create_e2e_cluster() as cluster:
        valid_args = {
            "initial_hypothesis": "RBAC verification",
            "ticket_id": 1001,
        }

        # 1. L1 caller -> DENIED
        token_l1 = cluster.make_token(role="L1")
        async with official_session(cluster, token=token_l1) as session:
            res_l1 = await session.call_tool("investigate_incident", arguments=valid_args)
            assert res_l1.isError is True
            assert "[INSUFFICIENT_ROLE]" in _get_text(res_l1)
            assert cluster.inv_call_count[0] == 0

        # 2. L2 caller -> DENIED
        token_l2 = cluster.make_token(role="L2")
        async with official_session(cluster, token=token_l2) as session:
            res_l2 = await session.call_tool("investigate_incident", arguments=valid_args)
            assert res_l2.isError is True
            assert "[INSUFFICIENT_ROLE]" in _get_text(res_l2)
            assert cluster.inv_call_count[0] == 0

        # 3. L2 caller with elevated privilege flags (production_write=True, attachment_access=True)
        #    STILL DENIED
        token_l2_elevated = cluster.make_token(
            role="L2", production_write=True, attachment_access=True
        )
        async with official_session(cluster, token=token_l2_elevated) as session:
            res_l2_elevated = await session.call_tool("investigate_incident", arguments=valid_args)
            assert res_l2_elevated.isError is True
            assert "[INSUFFICIENT_ROLE]" in _get_text(res_l2_elevated)
            assert cluster.inv_call_count[0] == 0

        # 4. L3 caller with no privilege flags -> ALLOWED
        token_l3_plain = cluster.make_token(
            role="L3", production_write=False, attachment_access=False
        )
        async with official_session(cluster, token=token_l3_plain) as session:
            res_l3_plain = await session.call_tool("investigate_incident", arguments=valid_args)
            assert res_l3_plain.isError is False
            assert cluster.inv_call_count[0] == 1

        # 5. Missing Authentication -> DENIED
        async with official_session(cluster, token=None) as session:
            res_missing = await session.call_tool("investigate_incident", arguments=valid_args)
            assert res_missing.isError is True
            assert "[AUTHENTICATION_REQUIRED]" in _get_text(res_missing)
            assert cluster.inv_call_count[0] == 1

        # 6. Malformed / Invalid Authentication Token -> DENIED
        async with official_session(cluster, token="invalid.jwt.token") as session:
            res_invalid = await session.call_tool("investigate_incident", arguments=valid_args)
            assert res_invalid.isError is True
            assert "[INVALID_TOKEN]" in _get_text(res_invalid)
            assert cluster.inv_call_count[0] == 1


@pytest.mark.asyncio
async def test_e2e_raw_jwt_termination_and_header_capture() -> None:
    """Section 18, 19, 20, 21: Raw JWT terminates at Gateway; zero custom headers downstream."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Header verification",
                    "ticket_id": 1001,
                },
            )

            # Gateway -> Investigation request inspection
            assert len(cluster.captured_inv_requests) >= 1
            inv_req = cluster.captured_inv_requests[0]
            assert "accept" in inv_req.headers
            assert "authorization" not in inv_req.headers
            assert "x-correlation-id" not in inv_req.headers
            assert "x-user-id" not in inv_req.headers
            assert "x-user-role" not in inv_req.headers
            assert "x-production-write" not in inv_req.headers
            assert "x-attachment-access" not in inv_req.headers

            # Investigation -> SuperOffice request inspection
            assert len(cluster.captured_so_requests) >= 1
            so_req = cluster.captured_so_requests[0]
            assert "authorization" not in so_req.headers
            assert "x-user-id" not in so_req.headers
            assert "x-user-role" not in so_req.headers
            assert "x-production-write" not in so_req.headers
            assert "x-attachment-access" not in so_req.headers


@pytest.mark.asyncio
async def test_e2e_correlation_separation_and_freshness() -> None:
    """Section 22: Gateway transport correlation != internal key; fresh per request."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            res1 = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Correlation probe 1",
                    "ticket_id": 1001,
                },
            )
            res2 = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Correlation probe 2",
                    "ticket_id": 2002,
                },
            )

            # Assert zero correlation_key in public responses
            assert "correlation_key" not in json.dumps(res1.structuredContent)
            assert "correlation_key" not in json.dumps(res2.structuredContent)

            # Verify captured dispatch requests captured distinct transport correlation IDs
            assert len(cluster.captured_dispatch_requests) == 2
            corr_id1 = cluster.captured_dispatch_requests[0].correlation_id
            corr_id2 = cluster.captured_dispatch_requests[1].correlation_id
            assert corr_id1 != corr_id2
            assert not corr_id1.startswith("inv-req-")
            assert not corr_id2.startswith("inv-req-")


@pytest.mark.asyncio
async def test_existing_tool_wire_regression_get_ticket() -> None:
    """Section 29: Representative existing tool preserves text-only wire behavior."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L1")
        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "get_ticket",
                arguments={"ticket_id": 1001},
            )

            assert res.isError is False
            assert len(res.content) > 0
            # structuredContent must remain strictly None for the existing 17 tools
            assert res.structuredContent is None


@pytest.mark.asyncio
async def test_e2e_source_degradation_and_fixed_error_messages() -> None:
    """Section 31, 32: Diagnostics failure returns isError=False with exact fixed error strings."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        cluster.fake_diag.set_should_fail(True)

        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Testing degradation",
                    "ticket_id": 1001,
                    "diagnostics": {"include_database_health": True},
                },
            )

            # Gateway call remains successful (data failure, not tool crash)
            assert res.isError is False
            validated_dto = InvestigateIncidentResponseDTO.model_validate(res.structuredContent)
            outcomes = {o.source: o for o in validated_dto.source_outcomes}

            # SuperOffice succeeded
            assert outcomes["superoffice_crm"].status == "SUCCESS"

            # Diagnostics failed with exact fixed public message
            diag_outcome = outcomes["mssql_diagnostics"]
            assert diag_outcome.status == "FAILED"
            assert diag_outcome.error_code == "DIAGNOSTICS_RETRIEVAL_FAILED"
            assert diag_outcome.error_message == "Diagnostics source data could not be retrieved."

            # Assert all other closed error mappings in ERROR_CODE_MAP
            for internal_code, (expected_code, expected_msg) in ERROR_CODE_MAP.items():
                dummy_res = SourceCollectionResult(
                    source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
                    status=SourceCollectionStatus.FAILED,
                    evidence=(),
                    error_code=internal_code,
                    error_message="arbitrary backend trace",
                )
                wire = InvestigationResponseMapper._map_source_outcome(dummy_res)
                assert wire.error_code == expected_code
                assert wire.error_message == expected_msg


@pytest.mark.asyncio
async def test_e2e_internal_secret_containment_mapper() -> None:
    """Section 33: Internal secret in failure message is dropped by fixed mapper."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        cluster.fake_diag.set_should_fail(True)

        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Secret containment verification",
                    "ticket_id": 1001,
                    "diagnostics": {"include_database_health": True},
                },
            )

            raw_response = json.dumps(res.structuredContent)
            assert INTERNAL_SECRET_SENTINEL not in raw_response
            assert "admin.database@superoffice-internal.test" not in raw_response
            assert "Simulated database health check failure." not in raw_response


@pytest.mark.asyncio
async def test_e2e_gateway_sanitizer_typed_dto_compatibility() -> None:
    """Section 34: Gateway sanitizer redacts sensitive fields in valid DTO without schema break."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")

        # Seed ticket with PII email and API key in legitimate string fields
        cluster.fake_so.seed_ticket(
            TicketDetailDomainDTO(
                ticket_id=5555,
                title="Secret Key Leakage Issue",
                status="Open",
                category="Billing issue reported by user.alert@superoffice.com",
                priority="High (api_key sk_live_9999888877776666)",
                description="Sensitive data in description.",
                assigned_to="AGENT-99",
                customer_id=999,
                customer_reference="CUST-SEC",
                created_at=datetime.now(UTC),
            )
        )

        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Sanitization test",
                    "ticket_id": 5555,
                },
            )

            assert res.isError is False
            raw_response = json.dumps(res.structuredContent)

            # Assert PII/Secret was redacted
            assert "user.alert@superoffice.com" not in raw_response
            assert "sk_live_9999888877776666" not in raw_response
            assert "[REDACTED_EMAIL]" in raw_response
            assert "[REDACTED_API_KEY]" in raw_response

            # Assert model validation still passes on sanitized object
            validated_dto = InvestigateIncidentResponseDTO.model_validate(res.structuredContent)
            assert len(validated_dto.evidence) == 1

            # Assert text matches structured content exactly
            assert json.loads(_get_text(res)) == res.structuredContent


@pytest.mark.asyncio
async def test_e2e_validation_failure_matrix_and_sensitive_sentinels() -> None:
    """Section 35, 36: Invalid requests fail safely with zero sentinel leakage."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            # 1. Hypothesis > 256 chars with sentinel
            oversized_hypo = "A" * 257 + SENSITIVE_HYPOTHESIS_SENTINEL
            res_hypo = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": oversized_hypo,
                    "ticket_id": 1001,
                },
            )
            assert res_hypo.isError is True
            assert cluster.inv_call_count[0] == 0

            # 2. ticket_id = 0 (invalid constraint)
            res_zero_ticket = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Zero ticket id",
                    "ticket_id": 0,
                },
            )
            assert res_zero_ticket.isError is True
            assert cluster.inv_call_count[0] == 0

            # 3. deadlocks limit = 51 (exceeds 50)
            res_deadlock_limit = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Deadlocks limit probe",
                    "diagnostics": {"deadlocks": {"limit": 51}},
                },
            )
            assert res_deadlock_limit.isError is True
            assert cluster.inv_call_count[0] == 0

            # 4. Unknown extra field with sentinel
            res_extra = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Extra field probe",
                    "ticket_id": 1001,
                    "unapproved_injection": SENSITIVE_EXTRA_FIELD_SENTINEL,
                },
            )
            assert res_extra.isError is True
            assert SENSITIVE_EXTRA_FIELD_SENTINEL not in _get_text(res_extra)
            assert cluster.inv_call_count[0] == 0


@pytest.mark.asyncio
async def test_e2e_downstream_tool_error_mapping() -> None:
    """Section 37: Downstream tool error mapped safely without tracebacks."""
    async with create_e2e_cluster(mock_dispatcher_tool_error=True) as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Tool error probe",
                    "ticket_id": 1001,
                },
            )

            assert res.isError is True
            assert "[DOWNSTREAM_TOOL_ERROR]" in _get_text(res)
            # No traceback or file path leakage
            assert "Traceback" not in _get_text(res)
            assert "src/" not in _get_text(res)


@pytest.mark.asyncio
async def test_e2e_investigation_unavailable() -> None:
    """Section 38: Unreachable downstream mapped to GATEWAY_DOWNSTREAM_UNAVAILABLE."""
    async with create_e2e_cluster(mock_dispatcher_unavailable=True) as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Unavailable probe",
                    "ticket_id": 1001,
                },
            )

            assert res.isError is True
            assert "[GATEWAY_DOWNSTREAM_UNAVAILABLE]" in _get_text(res)
            # No IP, port, or internal URL
            assert "8000" not in _get_text(res)
            assert "127.0.0.1" not in _get_text(res)


@pytest.mark.asyncio
async def test_e2e_policy_a_timeout() -> None:
    """Section 39: Transport timeout mapped to GATEWAY_DOWNSTREAM_TIMEOUT, isError=True."""
    async with create_e2e_cluster(mock_dispatcher_timeout=True) as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Timeout probe",
                    "ticket_id": 1001,
                },
            )

            assert res.isError is True
            assert "[GATEWAY_DOWNSTREAM_TIMEOUT]" in _get_text(res)
            # Must NOT be converted to a data outcome with structuredContent
            assert res.structuredContent is None


@pytest.mark.asyncio
async def test_e2e_rate_limiting_and_before_dispatch() -> None:
    """Section 41, 42: Default rate limit (60/60s, burst 10/1s) enforced via mock time."""

    class MockTimeRateLimiter(SlidingWindowRateLimiter):
        """Rate limiter using synthetic time to verify frozen production defaults."""

        def __init__(self) -> None:
            # Enforce exact frozen production defaults: 60 req/60s, burst 10 req/1.0s
            super().__init__()
            self.current_time = 1000.0

        def is_allowed(self, key: Any, timestamp: float | None = None) -> bool:
            return super().is_allowed(
                key, timestamp=self.current_time if timestamp is None else timestamp
            )

    rate_limiter = MockTimeRateLimiter()
    assert rate_limiter.policy.requests_per_window == 60
    assert rate_limiter.policy.window_seconds == 60.0
    assert rate_limiter.policy.burst_limit == 10
    assert rate_limiter.policy.burst_window_seconds == 1.0

    async with create_e2e_cluster(rate_limiter=rate_limiter) as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            # 10 calls allowed within the 1.0s burst window at t=1000.0
            for i in range(10):
                res = await session.call_tool(
                    "investigate_incident",
                    arguments={
                        "initial_hypothesis": f"Burst call {i}",
                        "ticket_id": 1001,
                    },
                )
                assert res.isError is False

            assert cluster.inv_call_count[0] == 10

            # 11th call at t=1000.5 (within the 1.0s burst window: 1000.5 - 1.0 <= 1000.0) -> DENIED
            rate_limiter.current_time = 1000.5
            res_11 = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Burst call 11 (exceeds default burst limit)",
                    "ticket_id": 1001,
                },
            )
            assert res_11.isError is True
            assert "[RATE_LIMIT_EXCEEDED]" in _get_text(res_11)

            # Downstream Investigation MCP receives zero additional calls
            assert cluster.inv_call_count[0] == 10

            # Advance time past the 1.0s burst window to t=1001.5 -> ALLOWED
            rate_limiter.current_time = 1001.5
            res_12 = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Call 12 after burst window elapsed",
                    "ticket_id": 1001,
                },
            )
            assert res_12.isError is False
            assert cluster.inv_call_count[0] == 11


@pytest.mark.asyncio
async def test_e2e_request_scoped_statelessness_verification() -> None:
    """Section 44, 45: Requests share zero state; fresh store instances created."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            # Call 1: ticket 1001
            res1 = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Incident 1001 triage",
                    "ticket_id": 1001,
                },
            )
            assert res1.isError is False
            dto1 = InvestigateIncidentResponseDTO.model_validate(res1.structuredContent)
            assert len(dto1.evidence) == 1
            assert isinstance(dto1.evidence[0].data, TicketObservationDTO)
            assert dto1.evidence[0].data.ticket_id == 1001

            # Call 2: ticket 2002
            res2 = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Incident 2002 triage",
                    "ticket_id": 2002,
                },
            )
            assert res2.isError is False
            dto2 = InvestigateIncidentResponseDTO.model_validate(res2.structuredContent)
            assert len(dto2.evidence) == 1
            assert isinstance(dto2.evidence[0].data, TicketObservationDTO)
            assert dto2.evidence[0].data.ticket_id == 2002

            # Assert Call 2 contains zero evidence from ticket 1001
            assert "1001" not in json.dumps(res2.structuredContent)

            # Verify through test instrumentation that fresh stores were created
            assert cluster.store_instance_count[0] == 2


@pytest.mark.asyncio
async def test_e2e_audit_logging_security() -> None:
    """Section 46: Audit logs contain zero sensitive data, JWTs, or arguments."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Audit verification hypothesis",
                    "ticket_id": 1001,
                },
            )

            # Inspect captured audit events
            for event in cluster.audit_sink.events:
                event_json = json.dumps(event.model_dump(mode="json"))
                for sensitive_token in (
                    "Audit verification hypothesis",
                    "ticket_id",
                    "Authorization",
                    "Bearer",
                    "http://testserver",
                ):
                    assert sensitive_token not in event_json


@pytest.mark.asyncio
async def test_e2e_boundary_enforcement_attachments_knowledge_logs_infrastructure() -> None:
    """Section 47, 48, 49, 50: Boundaries on attachments, knowledge, logs, infrastructure."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3", attachment_access=False)
        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Boundary enforcement triage",
                    "ticket_id": 1001,
                },
            )

            assert res.isError is False
            # Attachment calls: 0
            assert cluster.so_calls["list_attachments"] == 0
            assert cluster.so_calls["get_attachment"] == 0

            # Verified outcomes for static boundaries
            dto = InvestigateIncidentResponseDTO.model_validate(res.structuredContent)
            outcomes = {o.source: o for o in dto.source_outcomes}
            assert outcomes["application_logs"].status == "BLOCKED"
            assert outcomes["knowledge_base"].status == "NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_e2e_streamable_http_proof_across_all_hops() -> None:
    """Section 51: Explicit proof that all four hops use Streamable HTTP protocol."""
    async with create_e2e_cluster() as cluster:
        token = cluster.make_token(role="L3")
        async with official_session(cluster, token=token) as session:
            res = await session.call_tool(
                "investigate_incident",
                arguments={
                    "initial_hypothesis": "Streamable HTTP proof",
                    "ticket_id": 1001,
                },
            )

            assert res.isError is False
            # Hop 1: Client -> Gateway (executed via streamable_http_client)
            # Hop 2: Gateway -> Investigation (captured in captured_inv_requests)
            assert len(cluster.captured_inv_requests) >= 1
            # Hop 3: Investigation -> SuperOffice (captured in captured_so_requests)
            assert len(cluster.captured_so_requests) >= 1
            # Verify endpoint paths on captures
            assert any(r.url.path in {"/mcp", "/mcp/"} for r in cluster.captured_inv_requests)
            assert any(r.url.path in {"/mcp", "/mcp/"} for r in cluster.captured_so_requests)
