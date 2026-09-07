"""Unit tests for JsonStreamAuditSink and metadata-safe AuditEvent."""

import io
import json

import pytest

from platform_observability.audit import (
    AuditContext,
    AuditEvent,
    AuditSink,
    JsonStreamAuditSink,
)
from platform_observability.correlation import CorrelationContext


def test_audit_sink_implements_protocol() -> None:
    sink = JsonStreamAuditSink()
    assert isinstance(sink, AuditSink)


@pytest.mark.asyncio
async def test_valid_audit_event_emission_to_stream() -> None:
    buffer = io.StringIO()
    sink = JsonStreamAuditSink(stream=buffer)

    event = AuditEvent(
        event_type="TOOL_EXECUTION",
        action="get_ticket",
        status="SUCCESS",
        target_resource="ticket:10209",
        user_id="user_42",
        role="L1",
        target_server="superoffice",
        duration_ms=45.2,
        metadata_summary={"ticket_id": 10209, "result_status": "OPEN", "row_count": 1},
    )
    await sink.emit(event)

    output = buffer.getvalue()
    assert output.endswith("\n")
    data = json.loads(output.strip())

    assert data["event_type"] == "TOOL_EXECUTION"
    assert data["action"] == "get_ticket"
    assert data["status"] == "SUCCESS"
    assert data["target_resource"] == "ticket:10209"
    assert data["user_id"] == "user_42"
    assert data["role"] == "L1"
    assert data["target_server"] == "superoffice"
    assert data["duration_ms"] == 45.2
    assert data["metadata_summary"]["ticket_id"] == 10209
    assert data["metadata_summary"]["row_count"] == 1


def test_top_level_prohibited_secrets_rejected() -> None:
    # Attempting to include passwords, tokens, or private keys fails validation
    with pytest.raises(ValueError, match="Prohibited sensitive key"):
        AuditEvent(
            event_type="AUTH_CHECK",
            action="login",
            status="SUCCESS",
            metadata_summary={"user": "admin", "password": "SecretPassword!"},
        )

    with pytest.raises(ValueError, match="Prohibited sensitive key"):
        AuditEvent(
            event_type="TOOL_EXECUTION",
            action="get_ticket",
            status="SUCCESS",
            metadata_summary={"token": "eyJhbGciOi..."},
        )

    with pytest.raises(ValueError, match="Prohibited sensitive key"):
        AuditEvent(
            event_type="TOOL_EXECUTION",
            action="query_db",
            status="SUCCESS",
            metadata_summary={"connection_string": "Server=tcp:sql.prod..."},
        )

    with pytest.raises(ValueError, match="Prohibited sensitive key"):
        AuditEvent(
            event_type="AUTH_CHECK",
            action="verify_key",
            status="SUCCESS",
            metadata_summary={"api_key": "live_key_secret_123"},
        )


def test_nested_prohibited_secrets_rejected() -> None:
    # Nested secret inside arbitrary dictionaries/lists must be caught and rejected
    nested_auth = {
        "request": {
            "headers": {
                "authorization": "Bearer eyJhbGciOi...",
            }
        }
    }
    with pytest.raises(ValueError, match="Prohibited sensitive key"):
        AuditEvent(
            event_type="GATEWAY_DISPATCH",
            action="forward",
            status="SUCCESS",
            metadata_summary=nested_auth,
        )

    nested_pwd = {
        "credentials": {
            "database_password": "super-secret-password",
        }
    }
    with pytest.raises(ValueError, match="Prohibited sensitive key"):
        AuditEvent(
            event_type="DIAGNOSTIC_QUERY",
            action="connect",
            status="FAILED",
            metadata_summary=nested_pwd,
        )

    nested_list = {
        "params": [
            {"safe_param": 10},
            {"private_key": "---BEGIN PRIVATE KEY---"},
        ]
    }
    with pytest.raises(ValueError, match="Prohibited sensitive key"):
        AuditEvent(
            event_type="CRYPTO_OPERATION",
            action="sign",
            status="FAILED",
            metadata_summary=nested_list,
        )


@pytest.mark.asyncio
async def test_audit_context_binds_active_correlation_and_request_ids() -> None:
    buffer = io.StringIO()
    sink = JsonStreamAuditSink(stream=buffer)

    with CorrelationContext(correlation_id="corr-audit-999", request_id="req-audit-111"):
        ctx = AuditContext(
            event_type="TOOL_EXECUTION",
            action="search_knowledge",
            sink=sink,
            user_id="analyst_1",
            role="L2",
            target_server="knowledge",
        )
        await ctx.record_success(
            target_resource="kb:query",
            metadata_summary={"query_length": 15, "results_count": 3},
            duration_ms=120.0,
        )

    data = json.loads(buffer.getvalue().strip())
    assert data["metadata"]["correlation_id"] == "corr-audit-999"
    assert data["metadata"]["request_id"] == "req-audit-111"
    assert data["status"] == "SUCCESS"
    assert data["user_id"] == "analyst_1"
    assert data["role"] == "L2"
    assert data["target_server"] == "knowledge"


@pytest.mark.asyncio
async def test_audit_context_record_failure() -> None:
    buffer = io.StringIO()
    sink = JsonStreamAuditSink(stream=buffer)

    with CorrelationContext(correlation_id="corr-err-001", request_id="req-err-002"):
        ctx = AuditContext(
            event_type="RBAC_EVALUATION",
            action="find_deadlocks",
            sink=sink,
            user_id="user_l1",
            role="L1",
            target_server="diagnostics",
        )
        await ctx.record_failure(
            reason="Insufficient role rank: L1 cannot access L3 tool.",
            target_resource="diagnostics:find_deadlocks",
            metadata_summary={"attempted_tool": "find_deadlocks", "required_role": "L3"},
        )

    data = json.loads(buffer.getvalue().strip())
    assert data["status"] == "FAILED"
    assert "Insufficient role" in data["metadata_summary"]["failure_reason"]
    assert data["metadata"]["correlation_id"] == "corr-err-001"
    assert data["metadata"]["request_id"] == "req-err-002"
