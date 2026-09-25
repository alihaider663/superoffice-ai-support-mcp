"""Unit tests for the investigate_incident MCP tool wire contract and execution.

Covers input/output validation, error mapping, observability safety,
official MCP SDK client execution, and low-level Server boundary semantics.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.types import CallToolResult
from starlette.applications import Starlette

from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    DatabaseHealthDomainDTO,
    DeadlockDomainDTO,
    SlowQueryDomainDTO,
)
from investigation_mcp.adapters.diagnostics_mcp_adapter import DiagnosticsMcpClientAdapter
from investigation_mcp.adapters.superoffice_mcp_adapter import SuperOfficeMcpClientAdapter
from investigation_mcp.contracts.errors import (
    InvalidEvidenceObservationError,
)
from investigation_mcp.contracts.mappers import (
    InvestigationRequestMapper,
    InvestigationResponseMapper,
)
from investigation_mcp.server import (
    TOOL_DESCRIPTION_INVESTIGATE_INCIDENT,
    InvestigationMcpServer,
    _format_validation_error,
    create_app,
    create_investigation_mcp_server,
)
from platform_investigation import (
    IncidentCorrelationEngine,
    InvestigationOrchestratorEngine,
)
from platform_investigation.store import InMemoryInvestigationStore
from platform_investigation_service.service import InvestigationApplicationService
from so_mcp.contracts.dtos import MinimizedTicketDetailDTO


def _create_mock_service() -> InvestigationApplicationService:
    """Create a test InvestigationApplicationService with predictable mock data."""
    mock_so = AsyncMock(spec=SuperOfficeMcpClientAdapter)
    mock_so.get_ticket = AsyncMock(
        return_value=MinimizedTicketDetailDTO.model_validate(
            {
                "ticket_id": 777,
                "title": "ERP sync issue",
                "status": "Open",
                "category": "ERP",
                "priority": "High",
                "sanitized_description": "Timeout during sync",
                "created_at": "2026-09-01T10:00:00Z",
            }
        )
    )

    mock_diag = AsyncMock(spec=DiagnosticsMcpClientAdapter)
    mock_diag.get_database_health = AsyncMock(
        return_value=DatabaseHealthDomainDTO.model_validate(
            {
                "is_healthy": True,
                "status_summary": "ONLINE",
                "active_connections": 25,
                "latency_ms": 1.5,
                "collected_at": "2026-09-01T10:00:00Z",
            }
        )
    )
    mock_diag.find_deadlocks = AsyncMock(
        return_value=BoundedDiagnosticResultDTO[DeadlockDomainDTO].model_validate(
            {"items": [], "returned_count": 0, "is_truncated": False}
        )
    )
    mock_diag.find_slow_queries = AsyncMock(
        return_value=BoundedDiagnosticResultDTO[SlowQueryDomainDTO].model_validate(
            {"items": [], "returned_count": 0, "is_truncated": False}
        )
    )

    store = InMemoryInvestigationStore()
    orchestrator = InvestigationOrchestratorEngine(store=store)
    correlator = IncidentCorrelationEngine()

    return InvestigationApplicationService(
        orchestrator=orchestrator,
        superoffice_service=mock_so,
        diagnostics_service=mock_diag,
        correlator=correlator,
    )


def _extract_payload(result: Any) -> dict[str, Any]:
    """Helper extracting dict payload from tool call return."""
    if hasattr(result, "structuredContent") and result.structuredContent is not None:
        return result.structuredContent  # type: ignore[no-any-return]
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[1]
    if isinstance(result, list) and hasattr(result[0], "text"):
        parsed: dict[str, Any] = json.loads(str(result[0].text))
        return parsed
    res_final: dict[str, Any] = json.loads(str(result[0][0].text))
    return res_final


@pytest.mark.unit
async def test_investigate_incident_tool_metadata_and_schema():
    """Verify tool is registered with exact approved description and schema."""
    server = create_investigation_mcp_server()
    tools = await server.list_tools()

    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "investigate_incident"
    assert tool.description == TOOL_DESCRIPTION_INVESTIGATE_INCIDENT

    schema = tool.inputSchema
    assert schema.get("additionalProperties") is False
    properties = schema.get("properties", {})
    assert "initial_hypothesis" in properties
    assert "ticket_id" in properties
    assert "diagnostics" in properties

    # Confirm removed internal fields are NOT in schema
    assert "correlation_key" not in properties
    assert "max_steps" not in properties
    assert "investigation_id" not in properties
    assert "execution_status" not in properties


@pytest.mark.unit
async def test_investigate_incident_successful_tool_call():
    """Verify successful investigate_incident tool invocation returns public response DTO."""
    service = _create_mock_service()
    server = create_investigation_mcp_server(service=service)

    result = await server.call_tool(
        "investigate_incident",
        {
            "initial_hypothesis": "Checking database contention",
            "ticket_id": 777,
            "diagnostics": {"include_database_health": True},
        },
    )

    assert result is not None
    assert isinstance(result, CallToolResult)
    assert result.isError is False
    payload = _extract_payload(result)

    # Validate response shape
    assert "source_outcomes" in payload
    assert "evidence" in payload
    assert len(payload["source_outcomes"]) == 4

    # Verify absence of removed fields
    for forbidden in [
        "execution_status",
        "investigation_id",
        "plan",
        "timeline",
        "correlation_groups",
        "initial_hypothesis",
        "step_number",
    ]:
        assert forbidden not in payload

    # Verify evidence items have no wrapper observation_type, confidence, or evidence_id
    for ev in payload["evidence"]:
        assert "observation_type" not in ev
        assert "confidence" not in ev
        assert "evidence_id" not in ev
        assert "tags" not in ev
        assert "data" in ev
        assert "observation_type" in ev["data"]


@pytest.mark.unit
async def test_investigate_incident_zero_selection_raises_tool_error():
    """Verify degenerate zero-selection request returns modeled safe tool error."""
    service = _create_mock_service()
    server = create_investigation_mcp_server(service=service)

    res = await server.call_tool(
        "investigate_incident",
        {
            "initial_hypothesis": "No source selected",
            "ticket_id": None,
            "diagnostics": None,
        },
    )
    assert isinstance(res, CallToolResult)
    assert res.isError is True
    assert "At least one investigation target" in getattr(res.content[0], "text", "")


@pytest.mark.unit
async def test_investigate_incident_partial_collection_returns_200():
    """Verify partial collection returns valid response with partial evidence."""
    mock_so = AsyncMock(spec=SuperOfficeMcpClientAdapter)
    mock_so.get_ticket = AsyncMock(side_effect=RuntimeError("SO 503"))

    mock_diag = AsyncMock(spec=DiagnosticsMcpClientAdapter)
    mock_diag.get_database_health = AsyncMock(
        return_value=DatabaseHealthDomainDTO.model_validate(
            {
                "is_healthy": True,
                "status_summary": "ONLINE",
                "active_connections": 25,
                "latency_ms": 1.5,
                "collected_at": "2026-09-01T10:00:00Z",
            }
        )
    )
    mock_diag.find_deadlocks = AsyncMock(
        return_value=BoundedDiagnosticResultDTO[DeadlockDomainDTO].model_validate(
            {"items": [], "returned_count": 0, "is_truncated": False}
        )
    )
    mock_diag.find_slow_queries = AsyncMock(
        return_value=BoundedDiagnosticResultDTO[SlowQueryDomainDTO].model_validate(
            {"items": [], "returned_count": 0, "is_truncated": False}
        )
    )

    store = InMemoryInvestigationStore()
    orchestrator = InvestigationOrchestratorEngine(store=store)
    correlator = IncidentCorrelationEngine()
    service = InvestigationApplicationService(
        orchestrator=orchestrator,
        superoffice_service=mock_so,
        diagnostics_service=mock_diag,
        correlator=correlator,
    )
    server = create_investigation_mcp_server(service=service)

    result = await server.call_tool(
        "investigate_incident",
        {
            "initial_hypothesis": "Partial outage test",
            "ticket_id": 999,
            "diagnostics": {"include_database_health": True},
        },
    )

    assert result is not None
    assert isinstance(result, CallToolResult)
    assert result.isError is False
    payload = _extract_payload(result)

    outcomes = {o["source"]: o["status"] for o in payload["source_outcomes"]}
    assert outcomes["superoffice_crm"] == "FAILED"
    assert outcomes["mssql_diagnostics"] == "SUCCESS"
    assert outcomes["application_logs"] == "BLOCKED"
    assert outcomes["knowledge_base"] == "NOT_CONFIGURED"
    assert len(payload["evidence"]) == 1


@pytest.mark.unit
async def test_investigate_incident_all_source_non_success_returns_200_empty_evidence():
    """Verify all-source failure returns 200 response with empty evidence."""
    mock_so = AsyncMock(spec=SuperOfficeMcpClientAdapter)
    mock_so.get_ticket = AsyncMock(side_effect=RuntimeError("SO 503"))

    mock_diag = AsyncMock(spec=DiagnosticsMcpClientAdapter)
    mock_diag.get_database_health = AsyncMock(side_effect=RuntimeError("DB timeout"))

    store = InMemoryInvestigationStore()
    orchestrator = InvestigationOrchestratorEngine(store=store)
    correlator = IncidentCorrelationEngine()
    service = InvestigationApplicationService(
        orchestrator=orchestrator,
        superoffice_service=mock_so,
        diagnostics_service=mock_diag,
        correlator=correlator,
    )
    server = create_investigation_mcp_server(service=service)

    result = await server.call_tool(
        "investigate_incident",
        {
            "initial_hypothesis": "All sources fail",
            "ticket_id": 555,
            "diagnostics": {"include_database_health": True},
        },
    )

    assert result is not None
    assert isinstance(result, CallToolResult)
    assert result.isError is False
    payload = _extract_payload(result)
    assert len(payload["evidence"]) == 0
    outcomes = {o["source"]: o["status"] for o in payload["source_outcomes"]}
    assert outcomes["superoffice_crm"] == "FAILED"
    assert outcomes["mssql_diagnostics"] == "FAILED"


@pytest.mark.unit
async def test_investigate_incident_observability_no_pii_or_ids_logged(caplog):
    """Verify observability emits summary counts without leaking sensitive values or IDs."""
    service = _create_mock_service()
    server = create_investigation_mcp_server(service=service)

    hypothesis = "Observability security verification hypothesis"
    await server.call_tool(
        "investigate_incident",
        {
            "initial_hypothesis": hypothesis,
            "ticket_id": 777,
        },
    )

    all_logs = " ".join(record.message for record in caplog.records)

    # Verify free-text hypothesis is never logged
    assert hypothesis not in all_logs

    # Verify ticket description is never logged
    assert "Timeout during sync" not in all_logs


@pytest.mark.unit
async def test_investigate_incident_official_mcp_sdk_client_call():
    """Verify official MCP SDK client can call investigate_incident over Streamable HTTP."""
    service = _create_mock_service()
    server = create_investigation_mcp_server(service=service)
    app = server.streamable_http_app()

    async with (
        server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
        streamable_http_client("http://testserver/mcp", http_client=client) as (
            read_stream,
            write_stream,
            _,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        assert len(tools.tools) == 1
        assert tools.tools[0].name == "investigate_incident"

        res = await session.call_tool(
            "investigate_incident",
            {
                "initial_hypothesis": "Client integration test",
                "ticket_id": 777,
            },
        )
        assert res.isError is False
        assert len(res.content) > 0


@pytest.mark.unit
async def test_investigate_incident_dynamic_service_creation():
    """Verify server creates fresh request-scoped service when none injected."""
    mock_so = AsyncMock(spec=SuperOfficeMcpClientAdapter)
    mock_so.get_ticket = AsyncMock(
        return_value=MinimizedTicketDetailDTO.model_validate(
            {
                "ticket_id": 111,
                "title": "Incident",
                "status": "Open",
                "category": "DB",
                "priority": "Normal",
                "sanitized_description": "None",
                "created_at": "2026-09-01T10:00:00Z",
            }
        )
    )

    mock_diag = AsyncMock(spec=DiagnosticsMcpClientAdapter)
    mock_diag.get_database_health = AsyncMock(
        return_value=DatabaseHealthDomainDTO.model_validate(
            {
                "is_healthy": True,
                "status_summary": "ONLINE",
                "active_connections": 10,
                "latency_ms": 1.0,
                "collected_at": "2026-09-01T10:00:00Z",
            }
        )
    )

    server = create_investigation_mcp_server(
        service=None,
        superoffice_service=mock_so,
        diagnostics_service=mock_diag,
    )

    res = await server.call_tool(
        "investigate_incident",
        {
            "initial_hypothesis": "Testing dynamic service",
            "ticket_id": 111,
            "diagnostics": {"include_database_health": True},
        },
    )
    payload = _extract_payload(res)
    assert len(payload["source_outcomes"]) == 4


@pytest.mark.unit
async def test_investigate_incident_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify tool returns safe generic errors on mapper, service, or contract failures."""
    service = _create_mock_service()
    server = create_investigation_mcp_server(service=service)

    # 1. Request mapping failure
    def mock_bad_req_map(*args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        raise RuntimeError("Request mapping error")

    monkeypatch.setattr(InvestigationRequestMapper, "to_internal_request", mock_bad_req_map)
    res = await server.call_tool(
        "investigate_incident",
        {"initial_hypothesis": "Test", "ticket_id": 1},
    )
    assert isinstance(res, CallToolResult)
    assert res.isError is True
    assert "An unexpected internal error occurred" in getattr(res.content[0], "text", "")

    # 2. Service execution failure
    monkeypatch.undo()
    bad_service = _create_mock_service()
    monkeypatch.setattr(
        bad_service,
        "investigate",
        AsyncMock(side_effect=RuntimeError("DB exploded")),
    )
    server_bad_svc = create_investigation_mcp_server(service=bad_service)
    res_svc = await server_bad_svc.call_tool(
        "investigate_incident",
        {"initial_hypothesis": "Test", "ticket_id": 1},
    )
    assert isinstance(res_svc, CallToolResult)
    assert res_svc.isError is True
    assert "An unexpected internal error occurred" in getattr(res_svc.content[0], "text", "")

    # 3. Response mapping integrity failure
    monkeypatch.undo()

    def mock_bad_resp_map(*args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        raise InvalidEvidenceObservationError("Discriminator failed")

    monkeypatch.setattr(InvestigationResponseMapper, "to_public_response", mock_bad_resp_map)
    res_map = await server.call_tool(
        "investigate_incident",
        {"initial_hypothesis": "Test", "ticket_id": 1},
    )
    assert isinstance(res_map, CallToolResult)
    assert res_map.isError is True
    assert "An unexpected internal error occurred" in getattr(res_map.content[0], "text", "")

    # 4. Response unexpected serialization failure
    monkeypatch.undo()

    def mock_bad_ser(*args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        raise RuntimeError("Serialization failed")

    monkeypatch.setattr(InvestigationResponseMapper, "to_public_response", mock_bad_ser)
    res_ser = await server.call_tool(
        "investigate_incident",
        {"initial_hypothesis": "Test", "ticket_id": 1},
    )
    assert isinstance(res_ser, CallToolResult)
    assert res_ser.isError is True
    assert "An unexpected internal error occurred" in getattr(res_ser.content[0], "text", "")


@pytest.mark.unit
def test_create_app_returns_starlette() -> None:
    """Verify create_app instantiates Starlette application."""
    app = create_app()
    assert isinstance(app, Starlette)


@pytest.mark.unit
def test_format_validation_error_plain_value_error():
    """Verify plain error formatting fallback."""
    err = _format_validation_error(ValueError("Plain error"))
    assert err == "Invalid investigation request: Plain error"


@pytest.mark.unit
async def test_investigate_incident_output_schema_closed_typed() -> None:
    """Verify tool outputSchema is closed and typed with InvestigateIncidentResponseDTO."""
    server = create_investigation_mcp_server()
    tools = await server.list_tools()
    tool = tools[0]

    output_schema = tool.outputSchema
    assert output_schema is not None
    assert output_schema.get("title") == "InvestigateIncidentResponseDTO"
    assert output_schema.get("additionalProperties") is False
    props = output_schema.get("properties", {})
    assert set(props.keys()) == {"source_outcomes", "evidence", "hypothesis_evaluation"}

    defs = output_schema.get("$defs", {})
    assert "InvestigationSourceOutcomeWireDTO" in defs
    assert "DiagnosticEvidenceWireDTO" in defs
    assert "TicketObservationDTO" in defs
    assert "DatabaseHealthObservationDTO" in defs
    assert "DeadlockObservationDTO" in defs
    assert "SlowQueryObservationDTO" in defs
    assert "TicketAuditObservationDTO" in defs
    assert "TicketDiagnosticObservationDTO" in defs
    assert "BlockingSessionObservationDTO" in defs
    assert "LogExcerptObservationDTO" in defs
    assert "KnownIssueObservationDTO" in defs
    assert "KnowledgeArticleObservationDTO" in defs
    assert "HypothesisEvaluationWireDTO" in defs


@pytest.mark.unit
async def test_investigate_incident_rejects_extra_top_level_arguments() -> None:
    """Verify tool rejects extra top-level arguments fail-closed at runtime."""
    service = _create_mock_service()
    server = create_investigation_mcp_server(service=service)

    res = await server.call_tool(
        "investigate_incident",
        {
            "initial_hypothesis": "Database contention",
            "ticket_id": 777,
            "unexpected_internal_parameter": "should-be-rejected",
        },
    )
    assert isinstance(res, CallToolResult)
    assert res.isError is True
    text_extra = getattr(res.content[0], "text", "")
    assert "Extra inputs are not permitted" in text_extra
    assert "should-be-rejected" not in text_extra


@pytest.mark.unit
async def test_investigate_incident_streamable_http_structured_content() -> None:
    """Verify official MCP client receives structuredContent over Streamable HTTP."""
    service = _create_mock_service()
    server = create_investigation_mcp_server(service=service)
    app = server.streamable_http_app()

    async with (
        server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
        streamable_http_client("http://testserver/mcp", http_client=client) as (
            read_stream,
            write_stream,
            _,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        res = await session.call_tool(
            "investigate_incident",
            {
                "initial_hypothesis": "Database contention",
                "ticket_id": 777,
                "diagnostics": {"include_database_health": True},
            },
        )
        assert res.isError is False
        assert res.structuredContent is not None
        assert "source_outcomes" in res.structuredContent
        assert "evidence" in res.structuredContent
        for forbidden in ["investigation_id", "plan", "timeline", "correlation_key"]:
            assert forbidden not in res.structuredContent


# =========================================================================
# Phase 4.2 Security Amendment Tests
# =========================================================================


@pytest.mark.unit
def test_architecture_lowlevel_server_no_fastmcp_mutations() -> None:
    """Verify low-level Server boundary and absence of private FastMCP arg_model mutations."""
    server = create_investigation_mcp_server()
    assert isinstance(server, Server)
    assert isinstance(server, InvestigationMcpServer)

    # Inspect investigation_mcp package source code to verify zero reliance on FastMCP internals
    pkg_dir = Path(r"F:\superoffice-ai-support-mcp\src\servers\investigation\src\investigation_mcp")
    for py_file in pkg_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "_tool_manager" not in content, f"Found _tool_manager in {py_file}"
        assert "arg_model" not in content, f"Found arg_model in {py_file}"
        assert "model_rebuild" not in content, f"Found model_rebuild in {py_file}"


@pytest.mark.unit
async def test_sensitive_extra_field_sentinel_zero_leakage() -> None:
    """Verify extra-field sentinel value is never echoed in response or logs."""
    sentinel = "SENSITIVE_EXTRA_FIELD_SENTINEL_A71C"
    server = create_investigation_mcp_server()

    res = await server.call_tool(
        "investigate_incident",
        {
            "initial_hypothesis": "Database contention",
            "ticket_id": 777,
            "unexpected_param": sentinel,
        },
    )
    assert isinstance(res, CallToolResult)
    assert res.isError is True
    text_out = getattr(res.content[0], "text", "")
    assert sentinel not in text_out
    assert "Field 'unexpected_param': Extra inputs are not permitted" in text_out


@pytest.mark.unit
async def test_sensitive_hypothesis_sentinel_zero_leakage() -> None:
    """Verify sensitive hypothesis sentinel is never echoed on validation failure."""
    sentinel = "SENSITIVE_HYPOTHESIS_SENTINEL_9F41"
    server = create_investigation_mcp_server()

    # Hypothesis exceeding max_length=256 containing sentinel
    long_hypothesis = sentinel + ("X" * 250)
    res = await server.call_tool(
        "investigate_incident",
        {
            "initial_hypothesis": long_hypothesis,
            "ticket_id": 777,
        },
    )
    assert isinstance(res, CallToolResult)
    assert res.isError is True
    assert sentinel not in getattr(res.content[0], "text", "")
    err_text = getattr(res.content[0], "text", "")
    assert "Field 'initial_hypothesis': String should have at most 256 characters" in err_text


@pytest.mark.unit
async def test_validation_value_echo_matrix_all_six_cases() -> None:
    """Verify all 6 pre-function validation cases expose field & constraint without value echo."""
    server = create_investigation_mcp_server()

    cases: list[tuple[str, dict[str, Any], str, str]] = [
        (
            "ticket_id invalid type",
            {"initial_hypothesis": "Test", "ticket_id": "NOT_AN_INT"},
            "Field 'ticket_id'",
            "NOT_AN_INT",
        ),
        (
            "ticket_id below minimum",
            {"initial_hypothesis": "Test", "ticket_id": 0},
            "Field 'ticket_id'",
            "0",
        ),
        (
            "deadlock limit > 50",
            {"initial_hypothesis": "Test", "diagnostics": {"deadlocks": {"limit": 51}}},
            "Field 'diagnostics.deadlocks.limit'",
            "51",
        ),
        (
            "naive datetime",
            {
                "initial_hypothesis": "Test",
                "diagnostics": {"deadlocks": {"start_time": "2026-09-01T10:00:00"}},
            },
            "Field 'diagnostics.deadlocks.start_time'",
            "2026-09-01T10:00:00",
        ),
        (
            "initial_hypothesis > 256",
            {"initial_hypothesis": "H" * 257, "ticket_id": 1},
            "Field 'initial_hypothesis'",
            "H" * 257,
        ),
        (
            "unknown top-level argument",
            {
                "initial_hypothesis": "Test",
                "ticket_id": 1,
                "unexpected_param": "SECRET_SENTINEL_A71C",
            },
            "Field 'unexpected_param'",
            "SECRET_SENTINEL_A71C",
        ),
    ]

    for name, payload, expected_field, forbidden_val in cases:
        res = await server.call_tool("investigate_incident", payload)
        assert isinstance(res, CallToolResult), f"Case '{name}' did not return CallToolResult"
        assert res.isError is True, f"Case '{name}' did not fail"
        text = getattr(res.content[0], "text", "")
        assert expected_field in text, f"Case '{name}' missing field '{expected_field}' in: {text}"
        assert forbidden_val not in text, (
            f"Case '{name}' leaked forbidden value '{forbidden_val}' in: {text}"
        )


@pytest.mark.unit
async def test_investigate_incident_unknown_tool_rejection() -> None:
    """Verify unknown tool call fails safely with isError=True without exception dump."""
    server = create_investigation_mcp_server()
    res = await server.call_tool("unknown_tool", {})
    assert isinstance(res, CallToolResult)
    assert res.isError is True
    assert getattr(res.content[0], "text", "") == "Unknown tool: 'unknown_tool'."


@pytest.mark.unit
async def test_output_internal_field_exclusion() -> None:
    """Verify neither text nor structuredContent contains internal orchestrator fields."""
    service = _create_mock_service()
    server = create_investigation_mcp_server(service=service)

    res = await server.call_tool(
        "investigate_incident",
        {
            "initial_hypothesis": "Testing field exclusion",
            "ticket_id": 777,
            "diagnostics": {"include_database_health": True},
        },
    )
    assert isinstance(res, CallToolResult)
    assert res.isError is False
    assert res.structuredContent is not None

    forbidden_fields = [
        "investigation_id",
        "execution_status",
        "plan",
        "steps",
        "hypotheses",
        "timeline",
        "correlation_groups",
        "confidence_score",
        "evidence_id",
        "tags",
        "correlation_references",
        "correlation_key",
    ]

    # Check structuredContent
    for forbidden in forbidden_fields:
        assert forbidden not in res.structuredContent

    # Check text content
    text_content = getattr(res.content[0], "text", "")
    for forbidden in forbidden_fields:
        assert f'"{forbidden}"' not in text_content


@pytest.mark.unit
def test_endpoint_settings_proxy() -> None:
    """Verify EndpointSettings proxies underlying InvestigationServerSettings."""
    server = create_investigation_mcp_server()
    assert server.settings.port == 8005
    assert server.settings.timeout_seconds == 30
