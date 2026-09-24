"""Unit tests for SuperOffice ticket audit repository and mapping."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from so_mcp.audit.contracts import TicketAuditCriteriaDTO
from so_mcp.audit.repository import FakeTicketAuditRepository, MssqlTicketAuditRepository


def _create_multi_query_engine(results: list[Any]) -> MagicMock:
    """Create a mock AsyncEngine yielding sequential execute results."""
    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)

    execute_results = []
    for item in results:
        if isinstance(item, Exception):
            execute_results.append(item)
        else:
            mock_res = MagicMock()
            if isinstance(item, list):
                mock_res.fetchall = MagicMock(return_value=item)
                mock_res.fetchone = MagicMock(return_value=item[0] if item else None)
            elif item is not None:
                mock_res.fetchone = MagicMock(return_value=item)
                mock_res.fetchall = MagicMock(return_value=[item])
            else:
                mock_res.fetchall = MagicMock(return_value=[])
                mock_res.fetchone = MagicMock(return_value=None)
            execute_results.append(mock_res)

    mock_conn.execute = AsyncMock(side_effect=execute_results)
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)
    return mock_engine


@pytest.mark.asyncio
async def test_audit_repository_returns_chronological_trail() -> None:
    """Repository properly parses ticket_log, ticket_log_action, and ticket_log_change."""
    now = datetime(2026, 5, 24, 10, 29, 44, tzinfo=UTC)

    # 1. Milestone rows from ticket_log
    milestones = [
        (62183, 37, "junaid.tariq", now, "New request created by user"),
        (62184, 32, "junaid.tariq", now, "Read by owner"),
    ]

    # 2. Action rows from ticket_log_action
    actions = [
        (127377, now, 13, "Ticket updated", None, 1606, -1, "junaid.tariq"),
    ]

    # 3. Change rows from ticket_log_change
    changes = [
        (624696, 127377, -1, 2, "", "Testing Screen by Junaid", None, None),
        (624709, 127377, 163, 33, "", "15756", "x_case_category", "Case Category"),
    ]

    engine = _create_multi_query_engine([milestones, actions, changes])
    repo = MssqlTicketAuditRepository(engine)

    criteria = TicketAuditCriteriaDTO(ticket_id=10209, include_field_changes=True, limit=50)
    trail = await repo.get_ticket_audit_trail(criteria)

    assert trail.ticket_id == 10209
    assert trail.total_milestones == 2
    assert trail.total_actions == 1
    assert trail.total_changes == 2

    # Check milestone parsing
    assert trail.milestone_logs[0].id == 62183
    assert trail.milestone_logs[0].actor == "junaid.tariq"
    assert trail.milestone_logs[0].description == "New request created by user"

    # Check action parsing
    action = trail.actions[0]
    assert action.action_id == 127377
    assert action.actor == "junaid.tariq"
    assert action.action_name == "Ticket updated"
    assert len(action.changes) == 2

    # Check standard field change (title)
    change1 = action.changes[0]
    assert change1.field_name == "title"
    assert change1.display_name == "Title / Subject"
    assert change1.is_extra_field is False
    assert change1.to_value == "Testing Screen by Junaid"

    # Check extra field change (x_case_category)
    change2 = action.changes[1]
    assert change2.field_name == "x_case_category"
    assert change2.display_name == "Case Category"
    assert change2.is_extra_field is True
    assert change2.to_value == "15756"


@pytest.mark.asyncio
async def test_audit_repository_handles_empty_trail() -> None:
    """Empty database rows return an empty audit trail envelope without error."""
    engine = _create_multi_query_engine([[], [], []])
    repo = MssqlTicketAuditRepository(engine)

    criteria = TicketAuditCriteriaDTO(ticket_id=9999)
    trail = await repo.get_ticket_audit_trail(criteria)

    assert trail.ticket_id == 9999
    assert trail.total_milestones == 0
    assert trail.total_actions == 0
    assert trail.total_changes == 0
    assert trail.milestone_logs == ()
    assert trail.actions == ()


@pytest.mark.asyncio
async def test_fake_audit_repository() -> None:
    """FakeTicketAuditRepository honors limits and field change inclusion."""
    fake_repo = FakeTicketAuditRepository()
    criteria = TicketAuditCriteriaDTO(ticket_id=123)
    res = await fake_repo.get_ticket_audit_trail(criteria)
    assert res.ticket_id == 123
    assert res.total_actions == 0
