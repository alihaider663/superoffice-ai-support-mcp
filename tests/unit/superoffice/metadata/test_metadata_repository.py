"""Unit tests for SuperOffice metadata repository implementations."""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import DBAPIError

from so_mcp.metadata.contracts import (
    AssociateDetailCriteriaDTO,
    SuperOfficeMetadataError,
    SystemEventsCriteriaDTO,
    TicketMetadataListsCriteriaDTO,
)
from so_mcp.metadata.repository import FakeMetadataRepository, MssqlMetadataRepository


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
                mock_res.first = MagicMock(return_value=item[0] if item else None)
            elif item is not None:
                mock_res.fetchone = MagicMock(return_value=item)
                mock_res.first = MagicMock(return_value=item)
                mock_res.fetchall = MagicMock(return_value=[item])
            else:
                mock_res.fetchall = MagicMock(return_value=[])
                mock_res.fetchone = MagicMock(return_value=None)
                mock_res.first = MagicMock(return_value=None)
            execute_results.append(mock_res)

    mock_conn.execute = AsyncMock(side_effect=execute_results)
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)
    return mock_engine


# ---------------------------------------------------------------------------
# FakeMetadataRepository Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_repo_get_associate_details() -> None:
    """Fake repo successfully resolves associates by associate_id, ejuser_id, or username."""
    repo = FakeMetadataRepository()

    # Find by associate_id
    by_id = await repo.get_associate_details(AssociateDetailCriteriaDTO(associate_id=1607))
    assert by_id is not None
    assert by_id.username == "junaid.tariq"
    assert by_id.first_name == "Junaid"

    # Find by username
    by_user = await repo.get_associate_details(AssociateDetailCriteriaDTO(username="junaid.tariq"))
    assert by_user is not None
    assert by_user.associate_id == 1607

    # Case-insensitivity check
    by_upper = await repo.get_associate_details(AssociateDetailCriteriaDTO(username="JUNAID.TARIQ"))
    assert by_upper is not None
    assert by_upper.associate_id == 1607

    # Nonexistent
    missing = await repo.get_associate_details(AssociateDetailCriteriaDTO(associate_id=99999))
    assert missing is None


@pytest.mark.asyncio
async def test_fake_repo_get_ticket_metadata_lists() -> None:
    """Fake repo filters lists based on requested list_type."""
    repo = FakeMetadataRepository()

    # All lists
    all_lists = await repo.get_ticket_metadata_lists(
        TicketMetadataListsCriteriaDTO(list_type="all")
    )
    assert all_lists.total_categories == 1
    assert all_lists.total_priorities == 2
    assert all_lists.total_statuses == 2
    assert all_lists.total_user_groups == 2

    # Category only
    cat_only = await repo.get_ticket_metadata_lists(
        TicketMetadataListsCriteriaDTO(list_type="category")
    )
    assert len(cat_only.categories) == 1
    assert len(cat_only.priorities) == 0
    assert len(cat_only.statuses) == 0
    assert len(cat_only.user_groups) == 0

    # Priority only
    pri_only = await repo.get_ticket_metadata_lists(
        TicketMetadataListsCriteriaDTO(list_type="priority")
    )
    assert len(pri_only.categories) == 0
    assert len(pri_only.priorities) == 2


@pytest.mark.asyncio
async def test_fake_repo_list_system_events_and_triggers() -> None:
    """Fake repo filters scheduled tasks by disabled status, errors, and search query."""
    repo = FakeMetadataRepository()

    # Default: includes disabled because Task 43 is disabled and default include_disabled=True
    events = await repo.list_system_events_and_triggers(
        SystemEventsCriteriaDTO(include_disabled=True)
    )
    assert events.returned_tasks >= 1
    assert events.tasks[0].task_name == "Calculate Dashboard"

    # Filter out disabled
    no_disabled = await repo.list_system_events_and_triggers(
        SystemEventsCriteriaDTO(include_disabled=False)
    )
    assert no_disabled.returned_tasks == 0

    # Filter by query
    query_match = await repo.list_system_events_and_triggers(
        SystemEventsCriteriaDTO(query="Dashboard")
    )
    assert query_match.returned_tasks == 1

    query_mismatch = await repo.list_system_events_and_triggers(
        SystemEventsCriteriaDTO(query="NonExistent")
    )
    assert query_mismatch.returned_tasks == 0


# ---------------------------------------------------------------------------
# MssqlMetadataRepository Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mssql_get_associate_details_found() -> None:
    """MssqlMetadataRepository fetches and maps associate record from JOINed tables."""
    row = (
        1607,  # associate_id (0)
        1606,  # ejuser_id (1)
        "Junaid Tariq",  # associate_name (2)
        "junaid.tariq",  # username (3)
        "junaid.tariq",  # loginname (4)
        "Junaid",  # first_name (5)
        "Tariq",  # last_name (6)
        "Technical Consultant",  # title (7)
        "junaid@example.com",  # email (8)
        4,  # group_id (9)
        1,  # user_status (10)
        15,  # default_category (11)
        "Services",  # group_name (12)
    )
    engine = _create_multi_query_engine([[row]])
    repo = MssqlMetadataRepository(engine)

    assoc = await repo.get_associate_details(AssociateDetailCriteriaDTO(associate_id=1607))
    assert assoc is not None
    assert assoc.associate_id == 1607
    assert assoc.ejuser_id == 1606
    assert assoc.username == "junaid.tariq"
    assert assoc.group_name == "Services"
    assert assoc.is_active is True


@pytest.mark.asyncio
async def test_mssql_get_associate_details_not_found() -> None:
    """MssqlMetadataRepository returns None when row does not exist."""
    engine = _create_multi_query_engine([[]])
    repo = MssqlMetadataRepository(engine)

    assoc = await repo.get_associate_details(AssociateDetailCriteriaDTO(username="ghost"))
    assert assoc is None


@pytest.mark.asyncio
async def test_mssql_get_associate_details_validation() -> None:
    """Providing neither associate_id nor username raises SuperOfficeMetadataError."""
    engine = _create_multi_query_engine([])
    repo = MssqlMetadataRepository(engine)

    with pytest.raises(SuperOfficeMetadataError) as exc:
        await repo.get_associate_details(AssociateDetailCriteriaDTO())
    assert exc.value.error_code == "INVALID_ARGUMENTS"


@pytest.mark.asyncio
async def test_mssql_get_ticket_metadata_lists_all() -> None:
    """MssqlMetadataRepository fetches all reference lists in sequential queries."""
    cat_rows = [(15, "Support", "Support", 0, 1, "support@example.com", 2)]
    pri_rows = [(1, "Normal", 1, 10, 0)]
    stat_rows = [(1, "Open", 1, 1, 1, 0), (2, "Closed", 2, 2, 0, 0)]
    grp_rows = [(4, "Services", 1)]

    engine = _create_multi_query_engine([cat_rows, pri_rows, stat_rows, grp_rows])
    repo = MssqlMetadataRepository(engine)

    lists = await repo.get_ticket_metadata_lists(TicketMetadataListsCriteriaDTO(list_type="all"))
    assert lists.total_categories == 1
    assert lists.categories[0].name == "Support"
    assert lists.total_priorities == 1
    assert lists.priorities[0].name == "Normal"
    assert lists.total_statuses == 2
    assert lists.statuses[1].name == "Closed"
    assert lists.total_user_groups == 1
    assert lists.user_groups[0].name == "Services"


@pytest.mark.asyncio
async def test_mssql_list_system_events_and_triggers() -> None:
    """MssqlMetadataRepository executes filtered task query and maps ScheduledTaskItemDTO."""
    now = datetime(2026, 9, 24, 12, 0, 0)
    task_row = (
        43,  # task_id
        43,  # schedule_id
        "Calculate Dashboard",  # task_name
        148,  # script_id
        "a5e3dba515f147f9a34348aa12720cc6",  # script_identifier
        "calculateDashboard",  # script_include_id
        1,  # is_disabled
        2,  # execution_status
        10,  # minute_interval
        now,  # last_execution
        now,  # next_execution
        45,  # execution_time_ms
        "EjScript runtime error: table missing",  # error_message
        now,  # last_error
        1,  # retries
    )
    engine = _create_multi_query_engine([[task_row]])
    repo = MssqlMetadataRepository(engine)

    res = await repo.list_system_events_and_triggers(
        SystemEventsCriteriaDTO(only_errors=True, limit=50)
    )
    assert res.returned_tasks == 1
    task = res.tasks[0]
    assert task.task_id == 43
    assert task.task_name == "Calculate Dashboard"
    assert task.is_disabled is True
    assert task.error_message == "EjScript runtime error: table missing"


@pytest.mark.asyncio
async def test_mssql_exception_handling_timeout() -> None:
    """Timeout exceptions are translated into DATABASE_TIMEOUT error codes."""
    engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(side_effect=TimeoutError("Connection timed out"))
    engine.connect = MagicMock(return_value=mock_conn)

    repo = MssqlMetadataRepository(engine)
    with pytest.raises(SuperOfficeMetadataError) as exc:
        await repo.get_associate_details(AssociateDetailCriteriaDTO(associate_id=1))
    assert exc.value.error_code == "DATABASE_TIMEOUT"


@pytest.mark.asyncio
async def test_mssql_exception_handling_dbapi_error() -> None:
    """DBAPI errors are translated into DBAPI_ERROR error codes."""
    engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    orig_err = Exception("MSSQL login failed")
    mock_conn.execute = AsyncMock(side_effect=DBAPIError("SELECT 1", {}, orig_err))
    engine.connect = MagicMock(return_value=mock_conn)

    repo = MssqlMetadataRepository(engine)
    with pytest.raises(SuperOfficeMetadataError) as exc:
        await repo.get_ticket_metadata_lists(TicketMetadataListsCriteriaDTO(list_type="category"))
    assert exc.value.error_code == "DBAPI_ERROR"
