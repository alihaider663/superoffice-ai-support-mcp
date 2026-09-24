"""Unit tests for TicketAuditService and PII scrubbing."""

import pytest

from so_mcp.audit.contracts import (
    TicketActionItemDTO,
    TicketAuditCriteriaDTO,
    TicketAuditTrailDTO,
    TicketFieldChangeDTO,
    TicketLogMilestoneDTO,
)
from so_mcp.audit.repository import FakeTicketAuditRepository
from so_mcp.audit.service import TicketAuditService


@pytest.mark.asyncio
async def test_audit_service_scrubs_pii_and_credentials() -> None:
    """Audit service scrubs phone numbers, emails, and credentials from field transitions."""
    unscrubbed_trail = TicketAuditTrailDTO(
        ticket_id=5005,
        milestone_logs=(
            TicketLogMilestoneDTO(
                id=1,
                occurred_at=None,
                actor="agent@example.com",
                event_code=1,
                description="Customer called from +47 22 33 44 55 regarding password change",
            ),
        ),
        actions=(
            TicketActionItemDTO(
                action_id=101,
                occurred_at=None,
                actor="john.doe@superoffice.no",
                user_id=10,
                customer_id=20,
                action_code=13,
                action_name="Ticket updated",
                description="Updated phone to +1 (555) 123-4567",
                details="Contact email: secret.user@corp.com",
                changes=(
                    TicketFieldChangeDTO(
                        id=201,
                        action_id=101,
                        field_name="x_msisdn",
                        display_name="MSISDN",
                        is_extra_field=True,
                        extra_field_id=4,
                        change_type_code=33,
                        from_value="+47 22 33 44 55",
                        to_value="+1 (555) 123-4567",
                    ),
                ),
            ),
        ),
        total_milestones=1,
        total_actions=1,
        total_changes=1,
    )

    fake_repo = FakeTicketAuditRepository(audit_trails={5005: unscrubbed_trail})
    service = TicketAuditService(repository=fake_repo)

    criteria = TicketAuditCriteriaDTO(ticket_id=5005)
    sanitized = await service.get_ticket_audit_trail(criteria)

    # 1. Milestone description must not contain phone number
    assert "+47 22 33 44 55" not in sanitized.milestone_logs[0].description
    assert "[REDACTED_PHONE]" in sanitized.milestone_logs[0].description

    # 2. Action description must not contain phone number
    assert "+1 (555) 123-4567" not in sanitized.actions[0].description
    assert "[REDACTED_PHONE]" in sanitized.actions[0].description

    # 3. Action details must not contain email
    assert "secret.user@corp.com" not in str(sanitized.actions[0].details)
    assert "[REDACTED_EMAIL]" in str(sanitized.actions[0].details)

    # 4. Field transitions must have scrubbed values
    change = sanitized.actions[0].changes[0]
    assert "+47 22 33 44 55" not in change.from_value
    assert "+1 (555) 123-4567" not in change.to_value
    assert "[REDACTED_PHONE]" in change.from_value
    assert "[REDACTED_PHONE]" in change.to_value
