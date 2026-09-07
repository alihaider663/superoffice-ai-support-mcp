"""SuperOffice IIS/W3C high-volume reverse chunk log reader (Gate 7A.4A)."""

import hashlib
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    LogRecordDomainDTO,
    LogSearchCriteriaDTO,
)
from diag_mcp.contracts.errors import LogSearchError
from diag_mcp.contracts.interfaces import LogSearchClient
from diag_mcp.settings import DiagnosticsServerSettings

SERVICE_NAME = "superoffice_iis"
MAX_HEADER_SCAN_BYTES = 8192
MAX_RESULT_LIMIT_BOUND = 50
DEFAULT_RESULT_LIMIT = 20


@dataclass(frozen=True, slots=True)
class _ScanContext:
    start_time: datetime
    end_time: datetime
    criteria: LogSearchCriteriaDTO
    current_count: int
    effective_limit: int
    bytes_remaining: int
    start_monotonic: float
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class _ParsedW3cFields:
    record_time: datetime
    method: str
    uri_stem: str
    status_code: int
    substatus: str
    win32_status: str
    time_taken_ms: str


class SuperOfficeIisW3cLogReader(LogSearchClient):
    """High-volume reverse chunk reader for SuperOffice IIS/W3C access logs.

    Operates incrementally from end of file backwards using fixed-size binary chunks.
    Enforces strict physical scan bounds (bytes, files, timeout, line size) independent
    of requested result limits (D02).
    """

    def __init__(
        self,
        settings: DiagnosticsServerSettings | None = None,
        *,
        log_dir: Path | None = None,
        enabled: bool | None = None,
        max_files: int | None = None,
        max_scan_bytes: int | None = None,
        scan_timeout_seconds: float | None = None,
        read_chunk_bytes: int | None = None,
        default_lookback_minutes: int | None = None,
        max_lookback_hours: int | None = None,
        max_line_bytes: int | None = None,
    ) -> None:
        cfg = settings or DiagnosticsServerSettings()
        self._enabled = enabled if enabled is not None else cfg.iis_log_enabled
        self._configured_dir = log_dir if log_dir is not None else cfg.iis_log_path
        self._max_files = max_files if max_files is not None else cfg.iis_max_files
        self._max_scan_bytes = (
            max_scan_bytes if max_scan_bytes is not None else cfg.iis_max_scan_bytes
        )
        self._scan_timeout_seconds = (
            scan_timeout_seconds
            if scan_timeout_seconds is not None
            else cfg.iis_scan_timeout_seconds
        )
        self._read_chunk_bytes = (
            read_chunk_bytes if read_chunk_bytes is not None else cfg.iis_read_chunk_bytes
        )
        self._default_lookback_minutes = (
            default_lookback_minutes
            if default_lookback_minutes is not None
            else cfg.iis_default_lookback_minutes
        )
        self._max_lookback_hours = (
            max_lookback_hours if max_lookback_hours is not None else cfg.iis_max_lookback_hours
        )
        self._max_line_bytes = (
            max_line_bytes if max_line_bytes is not None else cfg.iis_max_line_bytes
        )

    def validate_log_directory(self) -> Path:
        """Validate that the configured IIS log directory is safe, absolute, and accessible.

        Raises:
            LogSearchError: If directory is missing, relative, not existing, not a directory,
                or inaccessible, without exposing physical filesystem paths.
        """
        if not self._enabled:
            raise LogSearchError(
                "SuperOffice IIS log reader is not enabled.",
                error_code="IIS_LOG_READER_DISABLED",
            )
        if self._configured_dir is None:
            raise LogSearchError(
                "IIS log directory is not configured.",
                error_code="IIS_LOG_PATH_NOT_CONFIGURED",
            )

        path = self._configured_dir
        if not path.is_absolute():
            raise LogSearchError(
                "IIS log directory configuration is invalid.",
                error_code="IIS_LOG_PATH_INVALID",
            )

        try:
            resolved = path.resolve()
            if not resolved.exists() or not resolved.is_dir():
                raise LogSearchError(
                    "IIS log directory is inaccessible or does not exist.",
                    error_code="IIS_LOG_PATH_INACCESSIBLE",
                )
            with os.scandir(resolved):
                pass
            return resolved
        except (OSError, PermissionError) as exc:
            if isinstance(exc, LogSearchError):
                raise
            raise LogSearchError(
                "IIS log directory cannot be accessed.",
                error_code="IIS_LOG_PATH_INACCESSIBLE",
            ) from None

    async def search_logs(
        self, criteria: LogSearchCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[LogRecordDomainDTO]:
        """Search SuperOffice IIS/W3C access logs matching structured criteria."""
        start_monotonic = time.monotonic()
        log_dir = self.validate_log_directory()
        now = datetime.now(UTC)

        # 1. Bounded window calculation
        end_time = criteria.end_time or now
        start_time = criteria.start_time or (
            end_time - timedelta(minutes=self._default_lookback_minutes)
        )
        earliest_allowed = now - timedelta(hours=self._max_lookback_hours)
        start_time = max(start_time, earliest_allowed)

        # 2. Result limit calculation (D02: max 50)
        requested_limit = criteria.limit or DEFAULT_RESULT_LIMIT
        effective_limit = min(max(1, requested_limit), MAX_RESULT_LIMIT_BOUND)

        # 3. Candidate file selection
        candidates, excluded_candidate_count = self._select_candidate_files(
            log_dir=log_dir,
            start_time=start_time,
        )

        # 4. Reverse chunk scanning across candidates
        records, stop_reason, hit_time_boundary = self._scan_candidates(
            candidates=candidates,
            start_time=start_time,
            end_time=end_time,
            criteria=criteria,
            effective_limit=effective_limit,
            start_monotonic=start_monotonic,
        )

        # 5. Coverage / Truncation Semantics (Gate 7A.4A Section 10-12, 32)
        is_truncated = stop_reason in ("RESULT_LIMIT", "BYTE_LIMIT", "TIMEOUT") or (
            excluded_candidate_count > 0 and not hit_time_boundary
        )

        total_matched: int | None = None
        if not is_truncated:
            total_matched = len(records)

        return BoundedDiagnosticResultDTO[LogRecordDomainDTO](
            items=tuple(records),
            returned_count=len(records),
            total_matched=total_matched,
            is_truncated=is_truncated,
        )

    def _scan_candidates(
        self,
        candidates: list[Path],
        start_time: datetime,
        end_time: datetime,
        criteria: LogSearchCriteriaDTO,
        *,
        effective_limit: int,
        start_monotonic: float,
    ) -> tuple[list[LogRecordDomainDTO], str | None, bool]:
        """Scan candidate files until results or resource bounds are reached."""
        records: list[LogRecordDomainDTO] = []
        total_bytes_read = 0
        stop_reason: str | None = None
        hit_time_boundary = False

        for file_path in candidates:
            if len(records) >= effective_limit:
                stop_reason = "RESULT_LIMIT"
                break
            if total_bytes_read >= self._max_scan_bytes:
                stop_reason = "BYTE_LIMIT"
                break
            if (time.monotonic() - start_monotonic) >= self._scan_timeout_seconds:
                stop_reason = "TIMEOUT"
                break

            ctx = _ScanContext(
                start_time=start_time,
                end_time=end_time,
                criteria=criteria,
                current_count=len(records),
                effective_limit=effective_limit,
                bytes_remaining=(self._max_scan_bytes - total_bytes_read),
                start_monotonic=start_monotonic,
                timeout_seconds=self._scan_timeout_seconds,
            )

            file_results, bytes_scanned, file_boundary, file_stop = self._scan_file_reverse(
                file_path=file_path,
                ctx=ctx,
            )

            records.extend(file_results)
            total_bytes_read += bytes_scanned

            if file_boundary:
                hit_time_boundary = True
                break

            if file_stop is not None:
                stop_reason = file_stop
                break

        return records, stop_reason, hit_time_boundary

    def _select_candidate_files(
        self,
        log_dir: Path,
        start_time: datetime,
    ) -> tuple[list[Path], int]:
        """Select and sort candidate .log files newest-first within lookback window."""
        raw_candidates: list[tuple[float, Path]] = []
        try:
            with os.scandir(log_dir) as entries:
                for entry in entries:
                    if not entry.is_file() or not entry.name.lower().endswith(".log"):
                        continue
                    try:
                        stat = entry.stat()
                    except OSError:
                        continue

                    if stat.st_size == 0:
                        continue

                    mtime_utc = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
                    if mtime_utc < start_time:
                        continue

                    raw_candidates.append((stat.st_mtime, Path(entry.path)))
        except OSError:
            raise LogSearchError(
                "Failed to inspect IIS log candidate files.",
                error_code="IIS_CANDIDATE_INSPECTION_FAILED",
            ) from None

        raw_candidates.sort(key=lambda item: item[0], reverse=True)
        sorted_paths = [p for _, p in raw_candidates]

        if len(sorted_paths) > self._max_files:
            return sorted_paths[: self._max_files], len(sorted_paths) - self._max_files

        return sorted_paths, 0

    def _parse_w3c_header(self, file_path: Path) -> dict[str, int] | None:
        """Extract and dynamically parse the W3C #Fields: header directive."""
        try:
            with file_path.open("rb") as f:
                header_bytes = f.read(MAX_HEADER_SCAN_BYTES)
        except OSError:
            return None

        for line in header_bytes.split(b"\n"):
            line_stripped = line.strip()
            if line_stripped.startswith(b"#Fields:"):
                try:
                    fields_str = line_stripped.decode("utf-8")
                except UnicodeDecodeError:
                    return None
                parts = fields_str.split()
                if len(parts) <= 1:
                    return None
                field_names = [p.lower() for p in parts[1:]]
                return {name: idx for idx, name in enumerate(field_names)}

        return None

    def _scan_file_reverse(
        self,
        file_path: Path,
        ctx: _ScanContext,
    ) -> tuple[list[LogRecordDomainDTO], int, bool, str | None]:
        """Scan a single W3C file in reverse chunks newest-to-oldest."""
        field_map = self._parse_w3c_header(file_path)
        if field_map is None or "date" not in field_map or "time" not in field_map:
            return [], 0, False, None

        records: list[LogRecordDomainDTO] = []
        bytes_scanned = 0
        hit_time_boundary = False
        stop_reason: str | None = None

        try:
            with file_path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                cursor = f.tell()
                if cursor == 0:
                    return [], 0, False, None

                # Check if file has a trailing newline; if not, last segment is partial
                f.seek(cursor - 1)
                last_byte = f.read(1)
                file_has_trailing_nl = last_byte == b"\n"

                carry = b""
                first_chunk = True

                while cursor > 0:
                    if (ctx.current_count + len(records)) >= ctx.effective_limit:
                        stop_reason = "RESULT_LIMIT"
                        break
                    if bytes_scanned >= ctx.bytes_remaining:
                        stop_reason = "BYTE_LIMIT"
                        break
                    if (time.monotonic() - ctx.start_monotonic) >= ctx.timeout_seconds:
                        stop_reason = "TIMEOUT"
                        break

                    chunk_size = min(self._read_chunk_bytes, cursor)
                    cursor -= chunk_size
                    f.seek(cursor)
                    chunk = f.read(chunk_size)
                    bytes_scanned += len(chunk)

                    carry, lines = self._split_chunk_lines(chunk, carry, cursor)
                    if first_chunk and not file_has_trailing_nl and lines:
                        # Drop trailing partial line fragment at EOF
                        lines = lines[:-1]
                        first_chunk = False

                    boundary_hit = self._process_chunk_lines(
                        lines=lines,
                        field_map=field_map,
                        ctx=ctx,
                        current_matches=records,
                    )

                    if boundary_hit:
                        hit_time_boundary = True
                        break

                    if (ctx.current_count + len(records)) >= ctx.effective_limit:
                        stop_reason = "RESULT_LIMIT"
                        break

        except (OSError, FileNotFoundError):
            return records, bytes_scanned, False, None

        return records, bytes_scanned, hit_time_boundary, stop_reason

    def _process_chunk_lines(
        self,
        lines: list[bytes],
        field_map: dict[str, int],
        ctx: _ScanContext,
        current_matches: list[LogRecordDomainDTO],
    ) -> bool:
        """Process logical chunk lines in reverse order. Returns True if boundary reached."""
        for raw_line in reversed(lines):
            line_clean = raw_line.rstrip(b"\r")
            if (
                not line_clean
                or line_clean.startswith(b"#")
                or len(line_clean) > self._max_line_bytes
            ):
                continue

            try:
                decoded_line = line_clean.decode("utf-8")
            except UnicodeDecodeError:
                continue

            rec, is_before, is_after = self._parse_and_filter_line(
                line=decoded_line,
                field_map=field_map,
                ctx=ctx,
            )

            if is_before:
                return True
            if is_after or rec is None:
                continue

            current_matches.append(rec)
            if (ctx.current_count + len(current_matches)) >= ctx.effective_limit:
                break

        return False

    def _split_chunk_lines(
        self,
        chunk: bytes,
        carry: bytes,
        cursor: int,
    ) -> tuple[bytes, list[bytes]]:
        """Split a reverse chunk into complete logical lines, managing carry fragments."""
        data = chunk + carry
        lines = data.split(b"\n")

        if cursor > 0:
            new_carry = lines[0]
            if len(new_carry) > self._max_line_bytes:
                new_carry = b""
            return new_carry, lines[1:]

        return b"", lines

    def _parse_and_filter_line(
        self,
        line: str,
        field_map: dict[str, int],
        ctx: _ScanContext,
    ) -> tuple[LogRecordDomainDTO | None, bool, bool]:
        """Extract fields, check time boundary, and match against criteria."""
        fields = self._extract_fields(line, field_map)
        if fields is None:
            return None, False, False

        if fields.record_time < ctx.start_time:
            return None, True, False
        if fields.record_time > ctx.end_time:
            return None, False, True

        severity = self._status_to_severity(fields.status_code)
        if not self._matches_criteria(fields, severity, ctx.criteria):
            return None, False, False

        record = self._build_record_dto(fields, severity, ctx.criteria.ticket_id)
        return record, False, False

    def _extract_fields(
        self,
        line: str,
        field_map: dict[str, int],
    ) -> _ParsedW3cFields | None:
        """Extract and parse structured fields from a logical W3C row."""
        tokens = line.split(" ")
        num_tokens = len(tokens)

        date_idx = field_map.get("date")
        time_idx = field_map.get("time")
        status_idx = field_map.get("sc-status")
        if (
            date_idx is None
            or time_idx is None
            or status_idx is None
            or date_idx >= num_tokens
            or time_idx >= num_tokens
            or status_idx >= num_tokens
        ):
            return None

        date_str = tokens[date_idx]
        time_str = tokens[time_idx]
        try:
            record_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=UTC
            )
        except ValueError:
            return None

        def get_val(name: str) -> str:
            idx = field_map.get(name)
            if idx is not None and idx < num_tokens:
                v = tokens[idx]
                return "" if v == "-" else v
            return ""

        cs_method = get_val("cs-method") or "UNKNOWN"
        cs_uri_stem = get_val("cs-uri-stem") or "/"
        sc_status_raw = get_val("sc-status") or "0"
        sc_substatus = get_val("sc-substatus") or "0"
        sc_win32_status = get_val("sc-win32-status") or "0"
        time_taken_raw = get_val("time-taken")

        try:
            status_code = int(sc_status_raw)
        except ValueError:
            status_code = 0

        return _ParsedW3cFields(
            record_time=record_time,
            method=cs_method,
            uri_stem=cs_uri_stem,
            status_code=status_code,
            substatus=sc_substatus,
            win32_status=sc_win32_status,
            time_taken_ms=time_taken_raw,
        )

    @staticmethod
    def _status_to_severity(status_code: int) -> str:
        """Map HTTP status code deterministically to log severity level."""
        if 100 <= status_code < 400:
            return "INFO"
        if 400 <= status_code < 500:
            return "WARN"
        if 500 <= status_code < 600:
            return "ERROR"
        return "INFO"

    @staticmethod
    def _matches_criteria(
        fields: _ParsedW3cFields,
        severity: str,
        criteria: LogSearchCriteriaDTO,
    ) -> bool:
        """Evaluate filters against structured W3C fields."""
        if criteria.service_name and criteria.service_name.strip().lower() != SERVICE_NAME:
            return False

        if criteria.severity and criteria.severity.strip().upper() != severity:
            return False

        if criteria.correlation_id:
            return False

        if criteria.ticket_id and str(criteria.ticket_id) not in fields.uri_stem:
            return False

        if criteria.query_text:
            query_literal = criteria.query_text.strip().lower()
            if query_literal:
                norm_msg = f"{fields.method} {fields.uri_stem} -> HTTP {fields.status_code}"
                searchable = (
                    f"{norm_msg} {fields.method} {fields.uri_stem} {fields.status_code}".lower()
                )
                if query_literal not in searchable:
                    return False

        return True

    @staticmethod
    def _build_record_dto(
        fields: _ParsedW3cFields,
        severity: str,
        ticket_id: int | None,
    ) -> LogRecordDomainDTO:
        """Construct normalized LogRecordDomainDTO without leaking secrets or queries."""
        if fields.time_taken_ms:
            message = (
                f"{fields.method} {fields.uri_stem} -> "
                f"HTTP {fields.status_code} ({fields.time_taken_ms} ms)"
            )
        else:
            message = f"{fields.method} {fields.uri_stem} -> HTTP {fields.status_code}"

        raw_context: dict[str, str] = {
            "sc_status": str(fields.status_code),
            "sc_substatus": fields.substatus,
            "sc_win32_status": fields.win32_status,
        }
        if fields.time_taken_ms:
            raw_context["time_taken_ms"] = fields.time_taken_ms

        id_payload = (
            f"{fields.record_time.isoformat()}|{fields.method}|{fields.uri_stem}|"
            f"{fields.status_code}|{fields.time_taken_ms}"
        )
        log_id = f"iis-{hashlib.sha256(id_payload.encode('utf-8')).hexdigest()[:16]}"

        return LogRecordDomainDTO(
            log_id=log_id,
            timestamp=fields.record_time,
            service_name=SERVICE_NAME,
            severity=severity,
            message=message,
            correlation_id=None,
            ticket_id=ticket_id,
            raw_context=raw_context,
        )
