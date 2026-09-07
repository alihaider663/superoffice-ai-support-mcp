"""Unit tests for SuperOffice IIS/W3C high-volume reverse chunk log reader (Gate 7A.4A)."""

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from diag_mcp.adapters.iis_log_reader import (
    MAX_RESULT_LIMIT_BOUND,
    SERVICE_NAME,
    SuperOfficeIisW3cLogReader,
)
from diag_mcp.contracts.dtos import LogSearchCriteriaDTO
from diag_mcp.contracts.errors import LogSearchError
from diag_mcp.settings import DiagnosticsServerSettings


def _ts(minutes_ago: int = 10) -> str:
    """Return a UTC timestamp string formatted for W3C logs within current lookback."""
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _create_w3c_file(
    path: Path,
    rows: list[str],
    fields_header: str = (
        "#Fields: date time cs-method cs-uri-stem cs-uri-query s-port "
        "cs-username c-ip cs(User-Agent) cs(Referer) sc-status sc-substatus "
        "sc-win32-status time-taken"
    ),
    line_ending: str = "\r\n",
) -> None:
    """Helper to create a synthetic W3C log file with headers and rows."""
    lines = [
        "#Software: Microsoft Internet Information Services 10.0",
        "#Version: 1.0",
        "#Date: 2026-09-07 00:00:00",
        fields_header,
    ]
    lines.extend(rows)
    content = line_ending.join(lines) + line_ending
    path.write_bytes(content.encode("utf-8"))


# ============================================================================
# 1. Settings & Directory Validation Tests
# ============================================================================


def test_settings_disabled_by_default() -> None:
    """Settings default to iis_log_enabled=False and iis_log_path=None with no hardcoded W3SVC."""
    settings = DiagnosticsServerSettings()
    assert settings.iis_log_enabled is False
    assert settings.iis_log_path is None
    assert settings.iis_max_files == 3
    assert settings.iis_max_scan_bytes == 33_554_432
    assert settings.iis_scan_timeout_seconds == 10.0


def test_settings_disabled_with_no_path_fails_closed(tmp_path: Path) -> None:
    """Reader fails closed if enabled=False."""
    reader = SuperOfficeIisW3cLogReader(enabled=False, log_dir=tmp_path)
    with pytest.raises(LogSearchError) as exc_info:
        reader.validate_log_directory()
    assert exc_info.value.error_code == "IIS_LOG_READER_DISABLED"


def test_enabled_with_missing_path_fails_closed() -> None:
    """Reader fails closed if enabled=True but log_dir is None."""
    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=None)
    with pytest.raises(LogSearchError) as exc_info:
        reader.validate_log_directory()
    assert exc_info.value.error_code == "IIS_LOG_PATH_NOT_CONFIGURED"


def test_relative_path_rejected() -> None:
    """Relative directory path is rejected."""
    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=Path("relative/logs/path"))
    with pytest.raises(LogSearchError) as exc_info:
        reader.validate_log_directory()
    assert exc_info.value.error_code == "IIS_LOG_PATH_INVALID"


def test_correct_specific_directory_accepted(tmp_path: Path) -> None:
    """An absolute existing directory is validated successfully."""
    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    validated = reader.validate_log_directory()
    assert validated == tmp_path.resolve()


def test_safe_errors_path_does_not_leak(tmp_path: Path) -> None:
    """Public error messages never expose the physical path or username."""
    non_existent = tmp_path / "secret_corp_dir" / "w3svc123"
    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=non_existent)
    with pytest.raises(LogSearchError) as exc_info:
        reader.validate_log_directory()
    assert "secret_corp_dir" not in str(exc_info.value)
    assert "w3svc123" not in str(exc_info.value)
    assert exc_info.value.error_code == "IIS_LOG_PATH_INACCESSIBLE"


# ============================================================================
# 2. Site Boundary Isolation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sibling_directory_not_touched(tmp_path: Path) -> None:
    """Reader strictly isolates to configured directory; sibling directories are ignored."""
    site_dir = tmp_path / "W3SVC1"
    sibling_dir = tmp_path / "W3SVC2"
    site_dir.mkdir()
    sibling_dir.mkdir()

    sibling_file = sibling_dir / "u_ex260907.log"
    _create_w3c_file(
        sibling_file,
        [f"{_ts(10)} GET /Sibling/api - 443 - - - - 200 0 0 50"],
    )

    site_file = site_dir / "u_ex260907.log"
    _create_w3c_file(
        site_file,
        [f"{_ts(5)} GET /SuperOffice/api/v1/Ticket/10198 - 443 - - - - 200 0 0 100"],
    )

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=site_dir)
    criteria = LogSearchCriteriaDTO()
    res = await reader.search_logs(criteria)

    assert len(res.items) == 1
    assert "Ticket/10198" in res.items[0].message
    assert "Sibling" not in res.items[0].message


@pytest.mark.asyncio
async def test_parent_iis_root_not_traversed(tmp_path: Path) -> None:
    """Reader does not scan parent directory."""
    root_log = tmp_path / "root_ex260907.log"
    _create_w3c_file(root_log, [f"{_ts(10)} GET /ParentRoot - 443 - - - - 200 0 0 10"])

    site_dir = tmp_path / "W3SVC99"
    site_dir.mkdir()
    site_file = site_dir / "u_ex260907.log"
    _create_w3c_file(
        site_file,
        [f"{_ts(5)} GET /SuperOffice/api - 443 - - - - 200 0 0 20"],
    )

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=site_dir)
    res = await reader.search_logs(LogSearchCriteriaDTO())
    assert len(res.items) == 1
    assert "ParentRoot" not in res.items[0].message


# ============================================================================
# 3. Dynamic W3C Header Parsing & Missing Header Safety
# ============================================================================


@pytest.mark.asyncio
async def test_w3c_dynamic_field_order(tmp_path: Path) -> None:
    """Reader dynamically parses #Fields directive regardless of column order."""
    custom_header = (
        "#Fields: time-taken sc-status cs-method cs-uri-stem date time sc-substatus sc-win32-status"
    )
    row = f"450 500 POST /SuperOffice/api/v1/Auth/Login {_ts(10)} 0 0"
    log_file = tmp_path / "u_ex260907.log"
    _create_w3c_file(log_file, [row], fields_header=custom_header)

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO())

    assert len(res.items) == 1
    item = res.items[0]
    assert item.severity == "ERROR"
    assert item.message == "POST /SuperOffice/api/v1/Auth/Login -> HTTP 500 (450 ms)"
    assert item.raw_context["sc_status"] == "500"
    assert item.raw_context["time_taken_ms"] == "450"


@pytest.mark.asyncio
async def test_missing_fields_header_skips_file_safely(tmp_path: Path) -> None:
    """If a file has no #Fields: header, it is skipped safely without crashing search."""
    corrupt_file = tmp_path / "u_ex260906.log"
    corrupt_file.write_text("#Software: IIS\n#NoFieldsHeaderHere\nrandom data\n", encoding="utf-8")

    good_file = tmp_path / "u_ex260907.log"
    _create_w3c_file(
        good_file,
        [f"{_ts(5)} GET /SuperOffice/api/v1/Ticket/10198 - 443 - - - - 200 0 0 100"],
    )

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO())
    assert len(res.items) == 1
    assert "10198" in res.items[0].message


# ============================================================================
# 4. Severity Mapping Tests
# ============================================================================


@pytest.mark.asyncio
async def test_severity_mapping_1xx_2xx_3xx_info(tmp_path: Path) -> None:
    """1xx, 2xx, 3xx HTTP statuses map to INFO."""
    rows = [
        f"{_ts(10)} GET /test1 - 80 - - - - 200 0 0 10",
        f"{_ts(5)} GET /test2 - 80 - - - - 302 0 0 15",
    ]
    log_file = tmp_path / "u_ex260907.log"
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO())
    assert len(res.items) == 2
    assert res.items[0].severity == "INFO"
    assert res.items[1].severity == "INFO"


@pytest.mark.asyncio
async def test_severity_mapping_4xx_warn(tmp_path: Path) -> None:
    """4xx HTTP statuses map to WARN."""
    rows = [
        f"{_ts(10)} GET /test401 - 80 - - - - 401 0 0 20",
        f"{_ts(5)} GET /test404 - 80 - - - - 404 0 0 25",
    ]
    log_file = tmp_path / "u_ex260907.log"
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO())
    assert len(res.items) == 2
    assert res.items[0].severity == "WARN"
    assert res.items[1].severity == "WARN"


@pytest.mark.asyncio
async def test_severity_mapping_5xx_error_never_critical(tmp_path: Path) -> None:
    """5xx HTTP statuses map to ERROR; never CRITICAL."""
    rows = [
        f"{_ts(10)} GET /test500 - 80 - - - - 500 0 0 50",
        f"{_ts(5)} GET /test503 - 80 - - - - 503 0 0 60",
    ]
    log_file = tmp_path / "u_ex260907.log"
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO())
    assert len(res.items) == 2
    assert res.items[0].severity == "ERROR"
    assert res.items[1].severity == "ERROR"
    assert all(item.severity != "CRITICAL" for item in res.items)


# ============================================================================
# 5. Query String & Sensitive Context Minimization
# ============================================================================


@pytest.mark.asyncio
async def test_query_string_omitted_from_output(tmp_path: Path) -> None:
    """cs-uri-query is strictly omitted from normalized message and raw_context."""
    secret_query = "token=secret_jwt_token_12345&password=SuperSecretPassword"
    row = (
        f"{_ts(5)} GET /SuperOffice/api/v1/Ticket/10198 {secret_query} "
        "443 admin 10.0.0.1 agent - 200 0 0 150"
    )
    log_file = tmp_path / "u_ex260907.log"
    _create_w3c_file(log_file, [row])

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO())

    assert len(res.items) == 1
    item = res.items[0]
    assert "secret_jwt_token" not in item.message
    assert "SuperSecretPassword" not in item.message
    assert "token" not in item.message
    for val in item.raw_context.values():
        assert "secret_jwt_token" not in val
        assert "SuperSecretPassword" not in val

    res_query = await reader.search_logs(LogSearchCriteriaDTO(query_text="secret_jwt_token"))
    assert len(res_query.items) == 0


@pytest.mark.asyncio
async def test_time_taken_normalization(tmp_path: Path) -> None:
    """time-taken formatted cleanly in message and raw_context; handled if missing."""
    rows = [
        f"{_ts(10)} GET /api/with_time - 80 - - - - 200 0 0 450",
        f"{_ts(5)} GET /api/no_time - 80 - - - - 200 0 0 -",
    ]
    log_file = tmp_path / "u_ex260907.log"
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO())

    assert len(res.items) == 2
    no_time_item = res.items[0]
    with_time_item = res.items[1]
    assert no_time_item.message == "GET /api/no_time -> HTTP 200"
    assert "time_taken_ms" not in no_time_item.raw_context
    assert with_time_item.message == "GET /api/with_time -> HTTP 200 (450 ms)"
    assert with_time_item.raw_context["time_taken_ms"] == "450"


# ============================================================================
# 6. Malformed Record, Timestamp, and Encoding Handling
# ============================================================================


@pytest.mark.asyncio
async def test_malformed_record_and_timestamp_skipped_safely(tmp_path: Path) -> None:
    """Malformed rows and invalid timestamps are safely skipped without failing search."""
    rows = [
        "invalid row without tokens",
        "2026-99-99 99:99:99 GET /api/bad_date - 80 - - - - 200 0 0 10",
        f"{_ts(5)} GET /api/good - 80 - - - - 200 0 0 25",
    ]
    log_file = tmp_path / "u_ex260907.log"
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO())

    assert len(res.items) == 1
    assert "bad_date" not in res.items[0].message
    assert "good" in res.items[0].message


@pytest.mark.asyncio
async def test_undecodable_bytes_handled_safely(tmp_path: Path) -> None:
    """Lines with invalid UTF-8 byte sequences are skipped safely."""
    log_file = tmp_path / "u_ex260907.log"
    header = (
        "#Fields: date time cs-method cs-uri-stem cs-uri-query sc-status sc-substatus "
        "sc-win32-status time-taken\n"
    )
    good_line = f"{_ts(5)} GET /api/valid - 200 0 0 10\n"
    bad_line_bytes = (
        b"2026-09-07 07:00:00 GET /api/" + bytes([0xFF, 0xFE, 0xFA]) + b" - 200 0 0 10\n"
    )

    with log_file.open("wb") as f:
        f.write(header.encode("utf-8"))
        f.write(good_line.encode("utf-8"))
        f.write(bad_line_bytes)

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO())

    assert len(res.items) == 1
    assert "valid" in res.items[0].message


# ============================================================================
# 7. Reverse / Chunked Reader Boundary Tests (CRLF, LF, Chunks, Partial Lines)
# ============================================================================


@pytest.mark.asyncio
async def test_crlf_and_lf_line_endings(tmp_path: Path) -> None:
    """Both CRLF and LF endings are cleanly parsed without trailing carriage returns."""
    log_crlf = tmp_path / "u_ex_crlf.log"
    log_lf = tmp_path / "u_ex_lf.log"

    _create_w3c_file(
        log_crlf,
        [f"{_ts(10)} GET /crlf - 80 - - - - 200 0 0 10"],
        line_ending="\r\n",
    )
    _create_w3c_file(
        log_lf,
        [f"{_ts(5)} GET /lf - 80 - - - - 200 0 0 10"],
        line_ending="\n",
    )

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO())

    assert len(res.items) == 2
    for item in res.items:
        assert "\r" not in item.message
        assert "\n" not in item.message


@pytest.mark.asyncio
async def test_chunk_boundary_line_split(tmp_path: Path) -> None:
    """Line split across chunk boundary is properly carried over and parsed."""
    log_file = tmp_path / "u_ex260907.log"
    rows = [
        f"{_ts(20 - i)} GET /SuperOffice/api/v1/Item/{i} - 80 - - - - 200 0 0 {10 + i}"
        for i in range(10)
    ]
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(
        enabled=True,
        log_dir=tmp_path,
        read_chunk_bytes=64,
    )
    res = await reader.search_logs(LogSearchCriteriaDTO())

    assert len(res.items) == 10
    assert "Item/9" in res.items[0].message
    assert "Item/0" in res.items[9].message


@pytest.mark.asyncio
async def test_partial_final_line_handled_safely(tmp_path: Path) -> None:
    """Partial uncompleted trailing line at EOF is handled safely."""
    log_file = tmp_path / "u_ex260907.log"
    _create_w3c_file(
        log_file,
        [f"{_ts(5)} GET /api/complete - 80 - - - - 200 0 0 10"],
    )
    with log_file.open("ab") as f:
        f.write(b"2026-09-07 07:40:00 GET /api/incom")

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO())

    assert len(res.items) == 1
    assert "complete" in res.items[0].message


@pytest.mark.asyncio
async def test_oversized_line_skipped_safely(tmp_path: Path) -> None:
    """Line exceeding max_line_bytes (8 KiB) is dropped safely without unbounded buffer growth."""
    log_file = tmp_path / "u_ex260907.log"
    huge_stem = "/SuperOffice/" + ("a" * 9000)
    oversized_row = f"{_ts(10)} GET {huge_stem} - 80 - - - - 200 0 0 10"
    normal_row = f"{_ts(5)} GET /SuperOffice/api/v1/Normal - 80 - - - - 200 0 0 20"

    _create_w3c_file(log_file, [oversized_row, normal_row])

    reader = SuperOfficeIisW3cLogReader(
        enabled=True,
        log_dir=tmp_path,
        max_line_bytes=8192,
    )
    res = await reader.search_logs(LogSearchCriteriaDTO())

    assert len(res.items) == 1
    assert "Normal" in res.items[0].message


# ============================================================================
# 8. Active File / Concurrency / Disappearance Tests
# ============================================================================


@pytest.mark.asyncio
async def test_file_disappears_after_enumeration_handled_gracefully(tmp_path: Path) -> None:
    """If file is removed between scandir and open, FileNotFoundError is handled gracefully."""
    f1 = tmp_path / "u_ex260906.log"
    f2 = tmp_path / "u_ex260907.log"
    _create_w3c_file(f1, [f"{_ts(10)} GET /f1 - 80 - - - - 200 0 0 10"])
    _create_w3c_file(f2, [f"{_ts(5)} GET /f2 - 80 - - - - 200 0 0 10"])

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)

    orig_open = Path.open

    def mock_open(self: Path, *args, **kwargs):
        if self.name == "u_ex260907.log":
            raise FileNotFoundError("Simulated disappearance during active rotation")
        return orig_open(self, *args, **kwargs)

    with patch.object(Path, "open", mock_open):
        res = await reader.search_logs(LogSearchCriteriaDTO())

    assert len(res.items) == 1
    assert "f1" in res.items[0].message


# ============================================================================
# 9. Filtering, Matching, and Deterministic ID Tests
# ============================================================================


@pytest.mark.asyncio
async def test_service_name_filtering(tmp_path: Path) -> None:
    """service_name filter matches 'superoffice_iis'; other service names return 0 matches."""
    log_file = tmp_path / "u_ex260907.log"
    _create_w3c_file(log_file, [f"{_ts(5)} GET /api - 80 - - - - 200 0 0 10"])

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)

    res_matching = await reader.search_logs(LogSearchCriteriaDTO(service_name=SERVICE_NAME))
    assert len(res_matching.items) == 1
    assert res_matching.items[0].service_name == SERVICE_NAME

    res_other = await reader.search_logs(LogSearchCriteriaDTO(service_name="auth_service"))
    assert len(res_other.items) == 0


@pytest.mark.asyncio
async def test_literal_query_matching_case_insensitive(tmp_path: Path) -> None:
    """Literal query text search matches case-insensitively across normalized fields."""
    log_file = tmp_path / "u_ex260907.log"
    rows = [
        f"{_ts(10)} GET /SuperOffice/api/v1/Ticket/10198 - 80 - - - - 200 0 0 10",
        f"{_ts(5)} POST /SuperOffice/api/v1/Contact/500 - 80 - - - - 500 0 0 20",
    ]
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)

    res1 = await reader.search_logs(LogSearchCriteriaDTO(query_text="ticket/10198"))
    assert len(res1.items) == 1
    assert "10198" in res1.items[0].message

    res2 = await reader.search_logs(LogSearchCriteriaDTO(query_text="HTTP 500"))
    assert len(res2.items) == 1
    assert "Contact/500" in res2.items[0].message

    res_regex = await reader.search_logs(LogSearchCriteriaDTO(query_text=".*"))
    assert len(res_regex.items) == 0


@pytest.mark.asyncio
async def test_ticket_id_filter(tmp_path: Path) -> None:
    """ticket_id filter matches when ticket ID appears in uri-stem."""
    log_file = tmp_path / "u_ex260907.log"
    rows = [
        f"{_ts(10)} GET /SuperOffice/api/v1/Ticket/10198 - 80 - - - - 200 0 0 10",
        f"{_ts(5)} GET /SuperOffice/api/v1/Ticket/99999 - 80 - - - - 200 0 0 10",
    ]
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO(ticket_id=10198))
    assert len(res.items) == 1
    assert res.items[0].ticket_id == 10198
    assert "10198" in res.items[0].message


@pytest.mark.asyncio
async def test_deterministic_log_id(tmp_path: Path) -> None:
    """log_id is opaque, non-sensitive, and deterministic for identical records."""
    log_file = tmp_path / "u_ex260907.log"
    row = f"{_ts(5)} GET /SuperOffice/api/v1/Ticket/10198 - 80 - - - - 200 0 0 100"
    _create_w3c_file(log_file, [row])

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res1 = await reader.search_logs(LogSearchCriteriaDTO())
    res2 = await reader.search_logs(LogSearchCriteriaDTO())

    id1 = res1.items[0].log_id
    id2 = res2.items[0].log_id
    assert id1.startswith("iis-")
    assert len(id1) == 20
    assert id1 == id2


# ============================================================================
# 10. Truncation Matrix & Bounded Resource Limits (Gate 7A.4A Section 32)
# ============================================================================


@pytest.mark.asyncio
async def test_truncation_matrix_complete_window_processed(tmp_path: Path) -> None:
    """Case 1: Complete bounded window processed -> is_truncated=False, total_matched=len."""
    log_file = tmp_path / "u_ex260907.log"
    rows = [
        f"{_ts(10)} GET /api/1 - 80 - - - - 200 0 0 10",
        f"{_ts(5)} GET /api/2 - 80 - - - - 200 0 0 10",
    ]
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO(limit=10))

    assert len(res.items) == 2
    assert res.returned_count == 2
    assert res.total_matched == 2
    assert res.is_truncated is False


@pytest.mark.asyncio
async def test_truncation_matrix_result_limit_reached(tmp_path: Path) -> None:
    """Case 2: Result limit reached -> is_truncated=True, total_matched=None."""
    log_file = tmp_path / "u_ex260907.log"
    rows = [f"{_ts(10 - i)} GET /api/{i} - 80 - - - - 200 0 0 10" for i in range(5)]
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res = await reader.search_logs(LogSearchCriteriaDTO(limit=2))

    assert len(res.items) == 2
    assert res.returned_count == 2
    assert res.total_matched is None
    assert res.is_truncated is True


@pytest.mark.asyncio
async def test_truncation_matrix_byte_limit_reached(tmp_path: Path) -> None:
    """Case 3: Byte limit reached before time boundary -> is_truncated=True, total_matched=None."""
    log_file = tmp_path / "u_ex260907.log"
    rows = [
        f"{_ts(30 - i)} GET /SuperOffice/api/v1/Item/{i} - 80 - - - - 200 0 0 10" for i in range(20)
    ]
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(
        enabled=True,
        log_dir=tmp_path,
        max_scan_bytes=200,
        read_chunk_bytes=100,
    )
    res = await reader.search_logs(LogSearchCriteriaDTO(limit=50))

    assert res.is_truncated is True
    assert res.total_matched is None


@pytest.mark.asyncio
async def test_truncation_matrix_timeout_reached(tmp_path: Path) -> None:
    """Case 4: Scan timeout reached -> is_truncated=True, total_matched=None."""
    log_file = tmp_path / "u_ex260907.log"
    rows = [f"{_ts(10 - i)} GET /api/{i} - 80 - - - - 200 0 0 10" for i in range(5)]
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(
        enabled=True,
        log_dir=tmp_path,
        scan_timeout_seconds=1.0,
    )
    # Simulate time progressing beyond the timeout bound
    with patch(
        "diag_mcp.adapters.iis_log_reader.time.monotonic", side_effect=[0.0, 0.0, 5.0, 5.0, 5.0]
    ):
        res = await reader.search_logs(LogSearchCriteriaDTO(limit=50))

    assert res.is_truncated is True
    assert res.total_matched is None


@pytest.mark.asyncio
async def test_truncation_matrix_max_file_bound_excludes_candidates(tmp_path: Path) -> None:
    """Case 5: Candidate files > max_files -> is_truncated=True, total_matched=None."""
    for i in range(5):
        f = tmp_path / f"u_ex26090{i}.log"
        _create_w3c_file(f, [f"{_ts(50 - i * 5)} GET /api/{i} - 80 - - - - 200 0 0 10"])
        os.utime(f, (time.time() + i * 10, time.time() + i * 10))

    reader = SuperOfficeIisW3cLogReader(
        enabled=True,
        log_dir=tmp_path,
        max_files=3,
    )
    res = await reader.search_logs(LogSearchCriteriaDTO(limit=50))

    assert res.is_truncated is True
    assert res.total_matched is None


@pytest.mark.asyncio
async def test_empty_result_safety_untruncated_vs_truncated(tmp_path: Path) -> None:
    """Empty results cleanly distinguish uncompleted scan from no matching records."""
    log_file = tmp_path / "u_ex260907.log"
    _create_w3c_file(log_file, [f"{_ts(5)} GET /api/other - 80 - - - - 200 0 0 10"])

    # 1. Complete window scanned, no match found -> is_truncated=False
    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    res_clean = await reader.search_logs(LogSearchCriteriaDTO(query_text="NonExistent"))
    assert len(res_clean.items) == 0
    assert res_clean.returned_count == 0
    assert res_clean.total_matched == 0
    assert res_clean.is_truncated is False

    # 2. Timeout/resource bound hit before match found -> is_truncated=True
    reader_timeout = SuperOfficeIisW3cLogReader(
        enabled=True,
        log_dir=tmp_path,
        scan_timeout_seconds=1.0,
    )
    with patch(
        "diag_mcp.adapters.iis_log_reader.time.monotonic", side_effect=[0.0, 0.0, 5.0, 5.0, 5.0]
    ):
        res_truncated = await reader_timeout.search_logs(
            LogSearchCriteriaDTO(query_text="NonExistent")
        )
    assert len(res_truncated.items) == 0
    assert res_truncated.returned_count == 0
    assert res_truncated.total_matched is None
    assert res_truncated.is_truncated is True


# ============================================================================
# 11. Large File Bounded-Read Verification (Section 33 & 34)
# ============================================================================


@pytest.mark.asyncio
async def test_lookback_cutoff_halts_file_scan(tmp_path: Path) -> None:
    """Records older than start_time halt further backward scanning in the file."""
    log_file = tmp_path / "u_ex260907.log"
    rows = [
        f"{_ts(120)} GET /SuperOffice/api/v1/Old1 - 80 - - - - 200 0 0 10",
        f"{_ts(100)} GET /SuperOffice/api/v1/Old2 - 80 - - - - 200 0 0 10",
        f"{_ts(10)} GET /SuperOffice/api/v1/Recent - 80 - - - - 200 0 0 10",
    ]
    _create_w3c_file(log_file, rows)

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)
    criteria = LogSearchCriteriaDTO(
        start_time=datetime.now(UTC) - timedelta(minutes=30),
        end_time=datetime.now(UTC),
    )
    res = await reader.search_logs(criteria)

    assert len(res.items) == 1
    assert "Recent" in res.items[0].message
    assert res.is_truncated is False
    assert res.total_matched == 1


@pytest.mark.asyncio
async def test_active_growing_file_scenario(tmp_path: Path) -> None:
    """Simulate active IIS append: reader processes current tail without locking or error."""
    log_file = tmp_path / "u_ex_active.log"
    _create_w3c_file(log_file, [f"{_ts(15)} GET /api/v1/Init - 80 - - - - 200 0 0 10"])

    reader = SuperOfficeIisW3cLogReader(enabled=True, log_dir=tmp_path)

    res1 = await reader.search_logs(LogSearchCriteriaDTO())
    assert len(res1.items) == 1

    with log_file.open("ab") as f:
        f.write(f"{_ts(2)} POST /api/v1/Appended - 80 - - - - 200 0 0 25\r\n".encode())

    res2 = await reader.search_logs(LogSearchCriteriaDTO())
    assert len(res2.items) == 2
    assert "Appended" in res2.items[0].message


@pytest.mark.asyncio
async def test_large_file_bounded_read_verification(tmp_path: Path) -> None:
    """Verify reader operates incrementally without reading full large file."""
    large_file = tmp_path / "u_ex_large.log"
    rows = [
        f"{_ts(120)} GET /SuperOffice/api/v1/Older/{i} - 80 - - - - 200 0 0 10" for i in range(1995)
    ]
    recent_rows = [
        f"{_ts(5)} GET /SuperOffice/api/v1/RecentError/{i} - 80 - - - - 500 0 0 500"
        for i in range(5)
    ]
    _create_w3c_file(large_file, rows + recent_rows)

    file_size = large_file.stat().st_size
    assert file_size > 100_000

    bytes_read_counter = 0
    unique_files_opened: set[str] = set()
    file_open_count = 0
    orig_open = Path.open

    def counting_open(self: Path, *args, **kwargs):
        nonlocal file_open_count
        file_open_count += 1
        unique_files_opened.add(self.name)
        real_file = orig_open(self, *args, **kwargs)

        class CountingWrapper:
            def __init__(self, f: object) -> None:
                self._f = f

            def read(self, size: int = -1) -> bytes:
                nonlocal bytes_read_counter
                data: bytes = self._f.read(size)  # type: ignore[attr-defined]
                bytes_read_counter += len(data)
                return data

            def seek(self, *a: object, **k: object) -> int:
                val = int(self._f.seek(*a, **k))  # type: ignore[attr-defined]
                return val

            def tell(self) -> int:
                val = int(self._f.tell())  # type: ignore[attr-defined]
                return val

            def __enter__(self) -> "CountingWrapper":
                return self

            def __exit__(self, *a: object) -> None:
                self._f.__exit__(*a)  # type: ignore[attr-defined]

        return CountingWrapper(real_file)

    reader = SuperOfficeIisW3cLogReader(
        enabled=True,
        log_dir=tmp_path,
        read_chunk_bytes=4096,
        max_scan_bytes=33_554_432,
    )

    criteria = LogSearchCriteriaDTO(severity="ERROR", limit=5)
    with patch.object(Path, "open", counting_open):
        res = await reader.search_logs(criteria)

    assert len(res.items) == 5
    assert all(item.severity == "ERROR" for item in res.items)
    assert "RecentError/4" in res.items[0].message
    assert res.returned_count <= MAX_RESULT_LIMIT_BOUND

    # Verified Metrics:
    # 1. candidate files opened: exactly 1 unique candidate file
    assert len(unique_files_opened) == 1
    assert len(unique_files_opened) <= reader._max_files
    assert file_open_count == 2  # 1 bounded header read + 1 reverse scan
    assert bytes_read_counter <= reader._max_scan_bytes
    assert bytes_read_counter < (file_size // 4)
