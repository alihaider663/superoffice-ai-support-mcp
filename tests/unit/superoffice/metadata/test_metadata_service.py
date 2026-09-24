"""Unit tests for SuperOfficeMetadataService and factory wiring."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from so_mcp.metadata.contracts import (
    AssociateDetailCriteriaDTO,
    AssociateDetailDTO,
    ScheduledTaskItemDTO,
    SystemEventsCriteriaDTO,
    SystemEventsResultDTO,
    TicketCategoryItemDTO,
    TicketMetadataListsCriteriaDTO,
    TicketMetadataListsDTO,
    TicketPriorityItemDTO,
    TicketStatusItemDTO,
    UserGroupItemDTO,
)
from so_mcp.metadata.factory import create_metadata_service
from so_mcp.metadata.repository import FakeMetadataRepository
from so_mcp.metadata.service import SuperOfficeMetadataService
from so_mcp.settings import SuperOfficeCodebaseSyncSettings


@pytest.mark.asyncio
async def test_metadata_service_scrubs_associate_email_and_pii() -> None:
    """SuperOfficeMetadataService scrubs email and sensitive data from associate details."""
    raw_associate = AssociateDetailDTO(
        associate_id=1607,
        ejuser_id=1606,
        name="Junaid Tariq",
        username="junaid.tariq",
        first_name="Junaid",
        last_name="Tariq",
        title="Consultant",
        email="junaid.tariq@corp-internal.com",
        group_id=4,
        group_name="Services",
        is_active=True,
        default_category_id=15,
    )
    fake_repo = FakeMetadataRepository(associates=[raw_associate])
    service = SuperOfficeMetadataService(repository=fake_repo)

    result = await service.get_associate_details(AssociateDetailCriteriaDTO(associate_id=1607))
    assert result is not None
    assert result.associate_id == 1607
    assert result.username == "junaid.tariq"
    # Email must be redacted by RecursiveOutputSanitizer
    assert "corp-internal.com" not in result.email
    assert "[REDACTED_EMAIL]" in result.email


@pytest.mark.asyncio
async def test_metadata_service_returns_none_when_associate_missing() -> None:
    """Service returns None if repository does not find associate."""
    fake_repo = FakeMetadataRepository(associates=[])
    service = SuperOfficeMetadataService(repository=fake_repo)

    result = await service.get_associate_details(AssociateDetailCriteriaDTO(associate_id=9999))
    assert result is None


@pytest.mark.asyncio
async def test_metadata_service_scrubs_category_notification_emails() -> None:
    """Metadata lists sanitize notification emails in ticket categories."""
    raw_lists = TicketMetadataListsDTO(
        categories=(
            TicketCategoryItemDTO(
                category_id=1,
                name="Network Support",
                fullname="Infrastructure -> Network Support",
                parent_id=0,
                delegate_method=1,
                notification_email="network-admin@telecom.no",
                closing_status=0,
            ),
        ),
        priorities=(
            TicketPriorityItemDTO(
                priority_id=1,
                name="Urgent",
                status=1,
                sort_order=10,
                flags=1,
            ),
        ),
        statuses=(
            TicketStatusItemDTO(
                status_id=1,
                name="Open",
                status_type=1,
                ts_rank=1,
                time_counter=1,
                is_deleted=False,
            ),
        ),
        user_groups=(UserGroupItemDTO(group_id=1, name="Admins", rank=1),),
        total_categories=1,
        total_priorities=1,
        total_statuses=1,
        total_user_groups=1,
    )
    fake_repo = AsyncMock()
    fake_repo.get_ticket_metadata_lists.return_value = raw_lists
    service = SuperOfficeMetadataService(repository=fake_repo)

    res = await service.get_ticket_metadata_lists(TicketMetadataListsCriteriaDTO(list_type="all"))
    assert res.total_categories == 1
    cat = res.categories[0]
    assert "telecom.no" not in str(cat.notification_email)
    assert "[REDACTED_EMAIL]" in str(cat.notification_email)


@pytest.mark.asyncio
async def test_metadata_service_scrubs_scheduled_task_errors() -> None:
    """System event errors containing PII or secrets are redacted."""
    raw_events = SystemEventsResultDTO(
        total_tasks=1,
        returned_tasks=1,
        tasks=(
            ScheduledTaskItemDTO(
                task_id=10,
                schedule_id=10,
                task_name="Sync Mail",
                script_id=5,
                script_identifier="abc",
                script_include_id="syncMail",
                is_disabled=False,
                execution_status=2,
                minute_interval=5,
                last_execution="2026-09-24T10:00:00",
                next_execution="2026-09-24T10:05:00",
                execution_time_ms=120,
                error_message=(
                    "Failed login with user secret_agent@company.com and phone +47 11 22 33 44"
                ),
                last_error="2026-09-24T10:00:00",
                retries=0,
            ),
        ),
    )
    fake_repo = AsyncMock()
    fake_repo.list_system_events_and_triggers.return_value = raw_events
    service = SuperOfficeMetadataService(repository=fake_repo)

    res = await service.list_system_events_and_triggers(SystemEventsCriteriaDTO(only_errors=True))
    assert res.returned_tasks == 1
    err_msg = res.tasks[0].error_message or ""
    assert "secret_agent@company.com" not in err_msg
    assert "+47 11 22 33 44" not in err_msg
    assert "[REDACTED_EMAIL]" in err_msg
    assert "[REDACTED_PHONE]" in err_msg


def test_create_metadata_service_with_custom_repo() -> None:
    """create_metadata_service accepts custom repository directly."""
    repo = FakeMetadataRepository()
    service = create_metadata_service(repository=repo)
    assert isinstance(service, SuperOfficeMetadataService)
    assert service._repository is repo


def test_create_metadata_service_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_metadata_service falls back to FakeMetadataRepository on engine failure."""
    monkeypatch.setattr(
        "so_mcp.metadata.factory.create_mssql_sync_engine",
        MagicMock(side_effect=RuntimeError("Cannot connect")),
    )
    settings = SuperOfficeCodebaseSyncSettings(
        mssql_host="invalid-host",
    )
    service = create_metadata_service(settings=settings)
    assert isinstance(service, SuperOfficeMetadataService)
    assert isinstance(service._repository, FakeMetadataRepository)
