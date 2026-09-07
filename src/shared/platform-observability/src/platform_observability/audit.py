"""Structured audit event models and sink interfaces."""

import json
import sys
from datetime import UTC, datetime
from typing import Any, Protocol, TextIO, runtime_checkable
from uuid import uuid4

from pydantic import Field, field_validator

from platform_core.models import AuditMetadata, PlatformBaseModel
from platform_observability.correlation import get_correlation_id, get_request_id

PROHIBITED_AUDIT_KEYS = {
    "password",
    "pwd",
    "secret",
    "token",
    "access_token",
    "bearer",
    "api_key",
    "apikey",
    "jwt",
    "authorization",
    "auth",
    "client_secret",
    "private_key",
    "db_password",
    "database_password",
    "connection_string",
    "attachment_content",
    "raw_body",
}


def _validate_no_secrets_recursive(obj: Any, path: str = "") -> None:
    """Recursively traverse arbitrary dictionary and sequence structures to reject secrets."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            norm_key = str(k).lower().replace("-", "_").strip()
            current_path = f"{path}.{k}" if path else str(k)
            if norm_key in PROHIBITED_AUDIT_KEYS or any(
                norm_key.endswith(f"_{s}") or norm_key.startswith(f"{s}_")
                for s in PROHIBITED_AUDIT_KEYS
            ):
                raise ValueError(
                    f"Prohibited sensitive key '{k}' at '{current_path}' "
                    "cannot be included in audit metadata."
                )
            _validate_no_secrets_recursive(v, current_path)
    elif isinstance(obj, (list, tuple, set)):
        for idx, item in enumerate(obj):
            _validate_no_secrets_recursive(item, f"{path}[{idx}]")


class AuditEvent(PlatformBaseModel):
    """Structured audit trail record for security-sensitive actions."""

    event_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique audit event identifier",
    )
    event_type: str = Field(
        ...,
        description="Classification of audit action (e.g. TOOL_EXECUTION, AUTH_CHECK)",
    )
    action: str = Field(
        ...,
        description="Specific action executed (e.g. get_ticket, search_logs)",
    )
    status: str = Field(..., description="Outcome status (SUCCESS, DENIED, FAILED)")
    target_resource: str | None = Field(default=None, description="Resource affected or queried")
    user_id: str | None = Field(default=None, description="Authenticated subject user ID")
    role: str | None = Field(default=None, description="Authenticated principal role (L1, L2, L3)")
    target_server: str | None = Field(default=None, description="Target MCP server name")
    duration_ms: float | None = Field(default=None, ge=0.0, description="Execution duration in ms")
    metadata: AuditMetadata = Field(default_factory=AuditMetadata)
    metadata_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Sanitized non-sensitive key-value metadata summary",
    )

    @field_validator("metadata_summary")
    @classmethod
    def validate_no_secrets_in_summary(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate that metadata_summary has no sensitive secret keys recursively."""
        _validate_no_secrets_recursive(v)
        return v


@runtime_checkable
class AuditSink(Protocol):
    """Interface for audit event destinations (e.g. stderr JSON, database, security SIEM)."""

    async def emit(self, event: AuditEvent) -> None:
        """Asynchronously emit an audit event."""
        ...


class JsonStreamAuditSink(AuditSink):
    """Standard audit sink formatting events as newline-delimited JSON to an I/O stream."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stderr

    async def emit(self, event: AuditEvent) -> None:
        """Format event to JSON and write to stream with flush."""
        data = event.model_dump(mode="json")
        line = json.dumps(data, ensure_ascii=False)
        self.stream.write(line + "\n")
        self.stream.flush()


class AuditContext:
    """Helper context for capturing and emitting audit events bound to active correlation IDs."""

    def __init__(
        self,
        event_type: str,
        action: str,
        sink: AuditSink | None = None,
        *,
        user_id: str | None = None,
        role: str | None = None,
        target_server: str | None = None,
    ) -> None:
        self.event_type = event_type
        self.action = action
        self.sink = sink
        self.user_id = user_id
        self.role = role
        self.target_server = target_server
        self.start_time = datetime.now(UTC)

    async def record_success(
        self,
        target_resource: str | None = None,
        metadata_summary: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Record a successful operation outcome."""
        if self.sink:
            event = AuditEvent(
                event_type=self.event_type,
                action=self.action,
                status="SUCCESS",
                target_resource=target_resource,
                user_id=self.user_id,
                role=self.role,
                target_server=self.target_server,
                duration_ms=duration_ms,
                metadata=AuditMetadata(
                    correlation_id=get_correlation_id(),
                    request_id=get_request_id(),
                ),
                metadata_summary=metadata_summary or {},
            )
            await self.sink.emit(event)

    async def record_failure(
        self,
        reason: str,
        target_resource: str | None = None,
        metadata_summary: dict[str, Any] | None = None,
    ) -> None:
        """Record a failed or denied operation outcome."""
        if self.sink:
            summary = dict(metadata_summary or {})
            summary["failure_reason"] = reason
            event = AuditEvent(
                event_type=self.event_type,
                action=self.action,
                status="FAILED",
                target_resource=target_resource,
                user_id=self.user_id,
                role=self.role,
                target_server=self.target_server,
                metadata=AuditMetadata(
                    correlation_id=get_correlation_id(),
                    request_id=get_request_id(),
                ),
                metadata_summary=summary,
            )
            await self.sink.emit(event)
