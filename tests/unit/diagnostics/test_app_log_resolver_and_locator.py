"""Unit tests for SuperOffice warning-log resolver and candidate locator (Gate 7A.4B1)."""

import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from diag_mcp.adapters.app_log_locator import (
    WarningLogCandidateBatch,
    WarningLogCandidateLocator,
    WarningLogCandidateMetadata,
)
from diag_mcp.adapters.app_log_resolver import (
    FIXED_CONFIG_WARNING_SQL_STR,
    ApplicationLogLocationDTO,
    ApplicationLogLocationResolver,
)
from diag_mcp.adapters.factory import (
    create_application_log_resolver,
    create_warning_log_candidate_locator,
)
from diag_mcp.contracts.errors import LogSearchError
from diag_mcp.settings import DiagnosticsServerSettings


def _create_mock_engine(mock_cursor_result: Any = None, side_effect: Any = None) -> MagicMock:
    """Create a mocked AsyncEngine returning a mock connection with controlled query execution."""
    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)

    if side_effect:
        mock_conn.execute = AsyncMock(side_effect=side_effect)
    else:
        mock_result = MagicMock()
        if isinstance(mock_cursor_result, list):
            mock_result.fetchall = MagicMock(return_value=mock_cursor_result)
            mock_result.fetchone = MagicMock(
                return_value=mock_cursor_result[0] if mock_cursor_result else None
            )
        elif mock_cursor_result is not None:
            mock_result.fetchone = MagicMock(return_value=mock_cursor_result)
            mock_result.fetchall = MagicMock(return_value=[mock_cursor_result])
        else:
            mock_result.fetchall = MagicMock(return_value=[])
            mock_result.fetchone = MagicMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=mock_result)

    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)
    return mock_engine


# ============================================================================
# 1. SQL Safety & Invariance Tests (Section 4, 27)
# ============================================================================


def test_fixed_sql_query_invariance() -> None:
    """Verify authoritative fixed query contains explicit columns and schema, and no dynamic SQL."""
    sql_text = FIXED_CONFIG_WARNING_SQL_STR.strip()

    assert "[warning]" in sql_text
    assert "[dbo].[config]" in sql_text
    assert "SELECT *" not in sql_text
    assert "select *" not in sql_text.lower()
    assert "NOLOCK" not in sql_text.upper()
    assert "READ UNCOMMITTED" not in sql_text.upper()
    assert sql_text == "SELECT TOP (1) [warning] FROM [dbo].[config];"


# ============================================================================
# 2. Location Resolver Unit Tests (Section 6, 7, 8, 10, 11, 27)
# ============================================================================


@pytest.mark.asyncio
async def test_resolver_disabled_fails_closed() -> None:
    """Verify resolver fails closed with APPLICATION_LOG_DISABLED when disabled."""
    resolver = ApplicationLogLocationResolver(
        enabled=False,
        override_path=r"D:\SuperOffice\SO_CS\log\warning",
    )

    with pytest.raises(LogSearchError) as exc_info:
        await resolver.resolve_location()

    assert exc_info.value.error_code == "APPLICATION_LOG_DISABLED"
    assert "disabled" in exc_info.value.message.lower()
    assert "D:\\" not in exc_info.value.message


@pytest.mark.asyncio
async def test_resolver_override_precedence_and_parsing() -> None:
    """Verify runtime override takes precedence over database query."""
    engine = _create_mock_engine(mock_cursor_result=("D:\\FromDB\\log\\warning",))
    resolver = ApplicationLogLocationResolver(
        enabled=True,
        override_path=r"D:\SuperOffice\SO_CS\log\warning",
        engine=engine,
    )

    location = await resolver.resolve_location()

    assert isinstance(location, ApplicationLogLocationDTO)
    assert location.source == "OVERRIDE"
    assert location.filename_prefix == "warning"
    assert location.drive == "D:"
    assert str(location.parent_directory).replace("/", "\\") == r"D:\SuperOffice\SO_CS\log"
    assert location.raw_configured_path == r"D:\SuperOffice\SO_CS\log\warning"
    engine.connect.assert_not_called()


@pytest.mark.asyncio
async def test_resolver_mssql_lookup_success() -> None:
    """Verify resolver executes fixed SQL query against database when override is absent."""
    mock_engine = _create_mock_engine(mock_cursor_result=("D:\\SuperOffice\\SO_CS\\log\\warning",))
    resolver = ApplicationLogLocationResolver(
        enabled=True,
        override_path=None,
        engine=mock_engine,
    )

    location = await resolver.resolve_location()

    assert isinstance(location, ApplicationLogLocationDTO)
    assert location.source == "DATABASE"
    assert location.filename_prefix == "warning"
    assert location.drive == "D:"
    assert str(location.parent_directory).replace("/", "\\") == r"D:\SuperOffice\SO_CS\log"
    assert location.raw_configured_path == r"D:\SuperOffice\SO_CS\log\warning"
    mock_engine.connect.assert_called_once()


@pytest.mark.asyncio
async def test_resolver_mssql_null_config_warning() -> None:
    """Verify resolver raises APPLICATION_LOG_PATH_NOT_CONFIGURED when warning is NULL in DB."""
    mock_engine = _create_mock_engine(mock_cursor_result=(None,))
    resolver = ApplicationLogLocationResolver(
        enabled=True,
        override_path=None,
        engine=mock_engine,
    )

    with pytest.raises(LogSearchError) as exc_info:
        await resolver.resolve_location()

    assert exc_info.value.error_code == "APPLICATION_LOG_PATH_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_resolver_mssql_empty_and_whitespace_config_warning() -> None:
    """Verify resolver raises APPLICATION_LOG_PATH_NOT_CONFIGURED for empty DB values."""
    for empty_val in ("", "   ", "\t\n"):
        mock_engine = _create_mock_engine(mock_cursor_result=(empty_val,))
        resolver = ApplicationLogLocationResolver(
            enabled=True,
            override_path=None,
            engine=mock_engine,
        )

        with pytest.raises(LogSearchError) as exc_info:
            await resolver.resolve_location()

        assert exc_info.value.error_code == "APPLICATION_LOG_PATH_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "invalid_path",
    [
        "log\\warning",  # Relative path missing drive/root
        "warning",  # Relative basename only
        "D:warning",  # Drive-relative path
        "\\SuperOffice\\SO_CS\\log\\warning",  # Root-relative missing drive
        "..\\log\\warning",  # Parent-relative
        "D:\\SuperOffice\\SO_CS\\log\\",  # Trailing backslash
        "D:\\SuperOffice\\SO_CS\\log/",  # Trailing slash
        "D:\\",  # Root-only
        "D:",  # Drive-only
        "D:\\warning",  # Root parent
        "D:\\SuperOffice\\log\\warn*ing",  # Invalid wildcard
        "D:\\SuperOffice\\log\\warn?ing",  # Invalid question mark
        "D:\\SuperOffice\\log\\warn<ing",  # Invalid char
        "D:\\SuperOffice\\log\\warn>ing",  # Invalid char
        "D:\\SuperOffice\\log\\warn:ing",  # Invalid colon
        "D:\\SuperOffice\\log\\warn|ing",  # Invalid pipe
        'D:\\SuperOffice\\log\\warn"ing',  # Invalid quote
        "D:\\SuperOffice\\log\\" + ("a" * 260),  # Exceeds 255 chars
    ],
)
def test_parse_path_prefix_invalid_values_rejected(invalid_path: str) -> None:
    """Verify parse_path_prefix rejects invalid, relative, and malformed paths safely."""
    with pytest.raises(LogSearchError) as exc_info:
        ApplicationLogLocationResolver.parse_path_prefix(invalid_path)

    assert exc_info.value.error_code == "APPLICATION_LOG_LOCATION_INVALID"
    # Physical path elements must NOT be leaked in error message
    if "\\" in invalid_path or "/" in invalid_path or ":" in invalid_path:
        assert invalid_path not in exc_info.value.message


def test_parse_path_prefix_255_char_boundary() -> None:
    """Verify 255 character limit boundary (255 valid, 256 invalid)."""
    base = "D:\\SuperOffice\\log\\"
    valid_prefix = "w" * (255 - len(base))
    valid_path = base + valid_prefix
    assert len(valid_path) == 255

    _parent_dir, prefix, drive = ApplicationLogLocationResolver.parse_path_prefix(valid_path)
    assert prefix == valid_prefix
    assert drive == "D:"

    invalid_path = valid_path + "x"
    assert len(invalid_path) == 256
    with pytest.raises(LogSearchError) as exc_info:
        ApplicationLogLocationResolver.parse_path_prefix(invalid_path)
    assert exc_info.value.error_code == "APPLICATION_LOG_LOCATION_INVALID"


def test_directory_only_string_interpreted_as_path_plus_prefix() -> None:
    """Verify that a path like 'D:\\SuperOffice\\SO_CS\\log' is interpreted as path+prefix.

    Confirms that the final segment becomes the prefix ('log') and the parent is
    'D:\\SuperOffice\\SO_CS', demonstrating why directory-only paths are not valid
    overrides for warning log files (Gate 7A.4B1-C).
    """
    parent_dir, prefix, drive = ApplicationLogLocationResolver.parse_path_prefix(
        r"D:\SuperOffice\SO_CS\log"
    )
    assert prefix == "log"
    assert str(parent_dir).replace("/", "\\") == r"D:\SuperOffice\SO_CS"
    assert drive == "D:"


@pytest.mark.asyncio
async def test_resolver_query_failure_sanitized() -> None:
    """Verify database exception during query is sanitized and does not leak credentials."""
    mock_engine = _create_mock_engine(
        side_effect=Exception("Database error. Server: 10.0.0.5, User: sa, Password: secret")
    )
    resolver = ApplicationLogLocationResolver(
        enabled=True,
        override_path=None,
        engine=mock_engine,
    )

    with pytest.raises(LogSearchError) as exc_info:
        await resolver.resolve_location()

    assert exc_info.value.error_code == "APPLICATION_LOG_LOCATION_QUERY_FAILED"
    assert "10.0.0.5" not in exc_info.value.message
    assert "password" not in exc_info.value.message.lower()
    assert "secret" not in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_resolver_d01_timeout_behavior() -> None:
    """Verify query timeout is mapped safely to APPLICATION_LOG_LOCATION_QUERY_FAILED."""
    mock_engine = _create_mock_engine(side_effect=TimeoutError())
    resolver = ApplicationLogLocationResolver(
        enabled=True,
        override_path=None,
        engine=mock_engine,
        query_timeout_seconds=5,
    )

    with pytest.raises(LogSearchError) as exc_info:
        await resolver.resolve_location()

    assert exc_info.value.error_code == "APPLICATION_LOG_LOCATION_QUERY_FAILED"


@pytest.mark.asyncio
async def test_resolver_unconfigured_engine_when_override_absent() -> None:
    """Verify resolver fails closed if enabled and override is absent but engine is None."""
    resolver = ApplicationLogLocationResolver(
        enabled=True,
        override_path=None,
        engine=None,
    )

    with pytest.raises(LogSearchError) as exc_info:
        await resolver.resolve_location()

    assert exc_info.value.error_code == "APPLICATION_LOG_LOCATION_QUERY_FAILED"


# ============================================================================
# 3. Candidate Locator Unit Tests (Section 14, 17, 18, 19, 20, 21, 22, 27)
# ============================================================================


def test_locator_valid_fixture_and_exact_prefix_matching(tmp_path: Path) -> None:
    """Verify locator finds files matching exact prefix, ignoring non-prefix and directories."""
    (tmp_path / "warning.log").write_text("w1", encoding="utf-8")
    (tmp_path / "warning_2026-09-07.txt").write_text("w2", encoding="utf-8")
    (tmp_path / "warning-app.1").write_text("w3", encoding="utf-8")

    (tmp_path / "error.log").write_text("e1", encoding="utf-8")
    (tmp_path / "info.log").write_text("i1", encoding="utf-8")
    (tmp_path / "other_warning.log").write_text("o1", encoding="utf-8")

    locator = WarningLogCandidateLocator(max_files=10)
    batch = locator.locate_candidates(parent_directory=tmp_path, filename_prefix="warning")

    assert isinstance(batch, WarningLogCandidateBatch)
    assert batch.total_matching_files == 3
    assert batch.returned_count == 3
    assert batch.is_truncated is False
    assert batch.filename_prefix == "warning"

    returned_names = [c.filename for c in batch.candidates]
    assert "warning.log" in returned_names
    assert "warning_2026-09-07.txt" in returned_names
    assert "warning-app.1" in returned_names
    assert "error.log" not in returned_names
    assert "other_warning.log" not in returned_names


def test_locator_excludes_directories_and_no_recursion(tmp_path: Path) -> None:
    """Verify locator scans ONLY direct children and excludes directories with matching prefix."""
    (tmp_path / "warning_root.log").write_text("root", encoding="utf-8")

    sub_dir = tmp_path / "warning_subdir"
    sub_dir.mkdir()
    (sub_dir / "warning_nested.log").write_text("nested", encoding="utf-8")

    locator = WarningLogCandidateLocator(max_files=10)
    batch = locator.locate_candidates(parent_directory=tmp_path, filename_prefix="warning")

    assert batch.total_matching_files == 1
    assert batch.returned_count == 1
    assert batch.candidates[0].filename == "warning_root.log"


def test_locator_newest_first_sorting(tmp_path: Path) -> None:
    """Verify candidate files are sorted newest-first by LastWriteTime (mtime descending)."""
    f_old = tmp_path / "warning_old.log"
    f_mid = tmp_path / "warning_mid.log"
    f_new = tmp_path / "warning_new.log"

    f_old.write_text("old", encoding="utf-8")
    f_mid.write_text("mid", encoding="utf-8")
    f_new.write_text("new", encoding="utf-8")

    t_base = time.time() - 1000
    os.utime(f_old, (t_base, t_base))
    os.utime(f_mid, (t_base + 100, t_base + 100))
    os.utime(f_new, (t_base + 200, t_base + 200))

    locator = WarningLogCandidateLocator(max_files=10)
    batch = locator.locate_candidates(parent_directory=tmp_path, filename_prefix="warning")

    assert len(batch.candidates) == 3
    assert batch.candidates[0].filename == "warning_new.log"
    assert batch.candidates[1].filename == "warning_mid.log"
    assert batch.candidates[2].filename == "warning_old.log"
    assert batch.candidates[0].last_modified_utc > batch.candidates[1].last_modified_utc
    assert batch.candidates[1].last_modified_utc > batch.candidates[2].last_modified_utc


def test_locator_max_files_bounding_and_truncation(tmp_path: Path) -> None:
    """Verify candidate files are capped at max_files and is_truncated is True when exceeded."""
    for i in range(1, 6):
        f = tmp_path / f"warning_{i:02d}.log"
        f.write_text(f"content {i}", encoding="utf-8")
        t = time.time() - (10 - i) * 10
        os.utime(f, (t, t))

    locator = WarningLogCandidateLocator(max_files=3)
    batch = locator.locate_candidates(parent_directory=tmp_path, filename_prefix="warning")

    assert batch.total_matching_files == 5
    assert batch.returned_count == 3
    assert len(batch.candidates) == 3
    assert batch.is_truncated is True
    assert [c.filename for c in batch.candidates] == [
        "warning_05.log",
        "warning_04.log",
        "warning_03.log",
    ]


def test_locator_empty_valid_directory_semantics(tmp_path: Path) -> None:
    """Verify empty valid directory returns empty batch and does NOT raise an error."""
    locator = WarningLogCandidateLocator(max_files=3)
    batch = locator.locate_candidates(parent_directory=tmp_path, filename_prefix="warning")

    assert batch.total_matching_files == 0
    assert batch.returned_count == 0
    assert batch.candidates == ()
    assert batch.is_truncated is False


def test_locator_missing_directory_raises_inaccessible(tmp_path: Path) -> None:
    """Verify missing directory raises APPLICATION_LOG_PATH_INACCESSIBLE."""
    missing_dir = tmp_path / "does_not_exist"
    locator = WarningLogCandidateLocator()

    with pytest.raises(LogSearchError) as exc_info:
        locator.locate_candidates(parent_directory=missing_dir, filename_prefix="warning")

    assert exc_info.value.error_code == "APPLICATION_LOG_PATH_INACCESSIBLE"
    assert str(missing_dir) not in exc_info.value.message


def test_locator_relative_directory_raises_invalid() -> None:
    """Verify relative directory raises APPLICATION_LOG_PATH_INVALID."""
    locator = WarningLogCandidateLocator()

    with pytest.raises(LogSearchError) as exc_info:
        locator.locate_candidates(
            parent_directory=Path("relative/log/dir"),
            filename_prefix="warning",
        )

    assert exc_info.value.error_code == "APPLICATION_LOG_PATH_INVALID"


def test_locator_metadata_only_guarantee(tmp_path: Path) -> None:
    """Verify candidate metadata includes size, path, timestamp, and does not open content."""
    test_file = tmp_path / "warning_data.log"
    payload = "A" * 1234
    test_file.write_text(payload, encoding="utf-8")

    locator = WarningLogCandidateLocator()
    batch = locator.locate_candidates(parent_directory=tmp_path, filename_prefix="warning")

    assert len(batch.candidates) == 1
    meta = batch.candidates[0]
    assert isinstance(meta, WarningLogCandidateMetadata)
    assert meta.filename == "warning_data.log"
    assert meta.size_bytes == 1234
    assert isinstance(meta.last_modified_utc, datetime)
    assert meta.last_modified_utc.tzinfo == UTC
    assert meta.file_path == test_file


def test_locator_from_location_dto(tmp_path: Path) -> None:
    """Verify locate_from_location method correctly uses ApplicationLogLocationDTO."""
    (tmp_path / "warning_one.log").write_text("content", encoding="utf-8")

    dto = ApplicationLogLocationDTO(
        parent_directory=tmp_path,
        filename_prefix="warning",
        source="OVERRIDE",
        raw_configured_path=str(tmp_path / "warning"),
    )

    locator = WarningLogCandidateLocator()
    batch = locator.locate_from_location(dto)

    assert batch.total_matching_files == 1
    assert batch.candidates[0].filename == "warning_one.log"


# ============================================================================
# 4. Factory & Integration Helpers Tests
# ============================================================================


def test_factory_creation_helpers() -> None:
    """Verify factory helpers instantiate configured resolver and locator."""
    settings = DiagnosticsServerSettings(
        application_log_enabled=True,
        application_log_path_override=r"D:\SuperOffice\SO_CS\log\warning",
        application_max_files=5,
    )

    resolver = create_application_log_resolver(settings)
    locator = create_warning_log_candidate_locator(settings)

    assert isinstance(resolver, ApplicationLogLocationResolver)
    assert isinstance(locator, WarningLogCandidateLocator)
    assert resolver._enabled is True
    assert resolver._override_path == r"D:\SuperOffice\SO_CS\log\warning"
    assert locator._max_files == 5
