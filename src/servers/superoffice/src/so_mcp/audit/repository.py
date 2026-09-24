"""Repository layer for fetching SuperOffice ticket activity logs, actions, and changes."""

import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SaTimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine

from so_mcp.audit.contracts import (
    SUPEROFFICE_STANDARD_LOG_ACTION_MAP,
    SUPEROFFICE_STANDARD_LOG_CHANGE_MAP,
    SuperOfficeAuditError,
    TicketActionItemDTO,
    TicketAuditCriteriaDTO,
    TicketAuditTrailDTO,
    TicketFieldChangeDTO,
    TicketLogMilestoneDTO,
)

logger = logging.getLogger(__name__)


def _serialize_text(val: Any) -> str:
    """Format database cell value into safe string representation."""
    if val is None:
        return ""
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return str(val)


class TicketAuditRepositoryProtocol(Protocol):
    """Protocol defining ticket audit trail query operations."""

    async def get_ticket_audit_trail(
        self,
        criteria: TicketAuditCriteriaDTO,
    ) -> TicketAuditTrailDTO:
        """Fetch chronological audit trail including milestones, actions, and field changes."""
        ...


class MssqlTicketAuditRepository:
    """Production MSSQL repository querying ticket_log, ticket_log_action, and ticket_log_change."""

    def __init__(self, engine: AsyncEngine, query_timeout_seconds: float = 5.0) -> None:
        self._engine = engine
        self._query_timeout_seconds = query_timeout_seconds

    def _handle_exception(self, exc: Exception, operation: str) -> None:
        """Translate driver, DBAPI, and asyncio exceptions into SuperOfficeAuditError."""
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError, SaTimeoutError)):
            raise SuperOfficeAuditError(
                f"Database query timed out during {operation}.",
                error_code="DATABASE_TIMEOUT",
                details={"operation": operation, "timeout_seconds": self._query_timeout_seconds},
            ) from None

        if isinstance(exc, DBAPIError):
            orig = getattr(exc, "orig", None)
            sqlstate = ""
            if orig is not None and hasattr(orig, "args") and orig.args:
                sqlstate = str(orig.args[0])

            if "HYT00" in sqlstate or "HYT01" in sqlstate or "timeout" in str(orig).lower():
                raise SuperOfficeAuditError(
                    f"Database query timed out during {operation}.",
                    error_code="DATABASE_TIMEOUT",
                    details={
                        "operation": operation,
                        "timeout_seconds": self._query_timeout_seconds,
                    },
                ) from None

            raise SuperOfficeAuditError(
                f"Database error during {operation}: {exc}",
                error_code="SUPEROFFICE_AUDIT_QUERY_FAILED",
                details={"operation": operation},
            ) from exc

        raise SuperOfficeAuditError(
            f"Unexpected failure during {operation}: {exc}",
            error_code="SUPEROFFICE_AUDIT_INTERNAL_ERROR",
            details={"operation": operation},
        ) from exc

    async def get_ticket_audit_trail(  # noqa: PLR0915
        self,
        criteria: TicketAuditCriteriaDTO,
    ) -> TicketAuditTrailDTO:
        """Fetch chronological audit trail for ticket_id."""
        ticket_id = criteria.ticket_id
        limit = min(criteria.limit, 100)

        # 1. Fetch milestone entries from ticket_log
        milestone_sql = text("""
            SELECT id, log_code, log_who, log_when, log_description
            FROM dbo.ticket_log
            WHERE ticket_id = :ticket_id
            ORDER BY log_when ASC, id ASC;
        """)

        # 2. Fetch actions from ticket_log_action joined with ejuser for username resolution
        action_sql = text("""
            SELECT TOP (:limit)
                a.id AS action_id,
                a.log_when,
                a.log_action,
                a.description,
                a.details,
                a.user_id,
                a.customer_id,
                COALESCE(u.loginname, u.username, CAST(a.user_id AS VARCHAR(32))) AS actor
            FROM dbo.ticket_log_action a
            LEFT JOIN dbo.ejuser u ON a.user_id = u.id
            WHERE a.ticket_id = :ticket_id
            ORDER BY a.log_when ASC, a.id ASC;
        """)

        # 3. Fetch atomic changes from ticket_log_change joined with extra_fields
        changes_sql = text("""
            SELECT
                c.id,
                c.action_id,
                c.extra_field_id,
                c.log_change,
                c.from_value,
                c.to_value,
                f.field_name AS extra_field_name,
                f.name AS extra_display_name
            FROM dbo.ticket_log_change c
            LEFT JOIN dbo.extra_fields f ON c.extra_field_id = f.id
            WHERE c.ticket_id = :ticket_id
            ORDER BY c.id ASC;
        """)

        try:
            async with self._engine.connect() as conn:
                milestone_rows = (
                    await conn.execute(milestone_sql, {"ticket_id": ticket_id})
                ).fetchall()
                action_rows = (
                    await conn.execute(action_sql, {"ticket_id": ticket_id, "limit": limit})
                ).fetchall()

                change_rows = []
                if criteria.include_field_changes and action_rows:
                    change_rows = (
                        await conn.execute(changes_sql, {"ticket_id": ticket_id})
                    ).fetchall()
        except Exception as exc:
            self._handle_exception(exc, f"fetch audit trail for ticket {ticket_id}")

        # Assemble milestone entries
        milestones: list[TicketLogMilestoneDTO] = []
        for r in milestone_rows:
            milestones.append(
                TicketLogMilestoneDTO(
                    id=int(r[0]),
                    event_code=int(r[1]) if r[1] is not None else None,
                    actor=str(r[2]) if r[2] else None,
                    occurred_at=r[3] if isinstance(r[3], datetime) else None,
                    description=str(r[4] or ""),
                )
            )

        # Group field changes by action_id
        changes_by_action: dict[int, list[TicketFieldChangeDTO]] = defaultdict(list)
        total_change_count = 0
        for cr in change_rows:
            cid = int(cr[0])
            act_id = int(cr[1])
            extra_id = int(cr[2])
            change_code = int(cr[3]) if cr[3] is not None else None
            from_val = _serialize_text(cr[4])
            to_val = _serialize_text(cr[5])
            extra_name = str(cr[6]) if cr[6] else None
            extra_label = str(cr[7]) if cr[7] else None

            if extra_id > 0 and extra_name:
                field_name = extra_name
                display_name = extra_label or extra_name
                is_extra = True
            elif change_code is not None and change_code in SUPEROFFICE_STANDARD_LOG_CHANGE_MAP:
                std_name, std_label = SUPEROFFICE_STANDARD_LOG_CHANGE_MAP[change_code]
                field_name = std_name
                display_name = std_label
                is_extra = False
            else:
                code_str = str(change_code) if change_code is not None else "unknown"
                field_name = f"field_{code_str}"
                display_name = f"Field {code_str}"
                is_extra = False

            change_dto = TicketFieldChangeDTO(
                id=cid,
                action_id=act_id,
                field_name=field_name,
                display_name=display_name,
                is_extra_field=is_extra,
                extra_field_id=extra_id,
                change_type_code=change_code,
                from_value=from_val,
                to_value=to_val,
            )
            changes_by_action[act_id].append(change_dto)
            total_change_count += 1

        # Assemble action items
        actions: list[TicketActionItemDTO] = []
        for ar in action_rows:
            action_id = int(ar[0])
            occurred_at = ar[1] if isinstance(ar[1], datetime) else None
            action_code = int(ar[2]) if ar[2] is not None else None
            desc = str(ar[3] or "")
            details = str(ar[4]) if ar[4] else None
            user_id = int(ar[5])
            cust_id = int(ar[6])
            actor = str(ar[7] or f"User-{user_id}")

            action_name = SUPEROFFICE_STANDARD_LOG_ACTION_MAP.get(action_code or 0, "Ticket Action")

            action_changes = tuple(changes_by_action.get(action_id, []))
            actions.append(
                TicketActionItemDTO(
                    action_id=action_id,
                    occurred_at=occurred_at,
                    actor=actor,
                    user_id=user_id,
                    customer_id=cust_id,
                    action_code=action_code,
                    action_name=action_name,
                    description=desc,
                    details=details,
                    changes=action_changes,
                )
            )

        return TicketAuditTrailDTO(
            ticket_id=ticket_id,
            milestone_logs=tuple(milestones),
            actions=tuple(actions),
            total_milestones=len(milestones),
            total_actions=len(actions),
            total_changes=total_change_count,
        )


class FakeTicketAuditRepository:
    """In-memory fake repository for deterministic unit and contract testing."""

    def __init__(
        self,
        audit_trails: dict[int, TicketAuditTrailDTO] | None = None,
        should_fail: bool = False,
    ) -> None:
        self._audit_trails: dict[int, TicketAuditTrailDTO] = audit_trails or {}
        self._should_fail = should_fail

    async def get_ticket_audit_trail(
        self,
        criteria: TicketAuditCriteriaDTO,
    ) -> TicketAuditTrailDTO:
        if self._should_fail:
            raise SuperOfficeAuditError(
                "Simulated repository failure.",
                error_code="SUPEROFFICE_AUDIT_QUERY_FAILED",
            )
        trail = self._audit_trails.get(criteria.ticket_id)
        if trail is None:
            return TicketAuditTrailDTO(
                ticket_id=criteria.ticket_id,
                milestone_logs=(),
                actions=(),
                total_milestones=0,
                total_actions=0,
                total_changes=0,
            )
        actions = trail.actions[: criteria.limit]
        if not criteria.include_field_changes:
            actions = tuple(a.model_copy(update={"changes": ()}) for a in actions)
        return trail.model_copy(
            update={
                "actions": actions,
                "total_actions": len(actions),
                "total_changes": sum(len(a.changes) for a in actions),
            }
        )
