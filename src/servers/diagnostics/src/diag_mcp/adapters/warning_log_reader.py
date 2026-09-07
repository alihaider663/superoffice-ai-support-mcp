"""SuperOffice warning log streaming reader (Gate 7A.4B2 / 7A.4B2-R1 / 7A.4B2-R2).

Bounded reader for SuperOffice warning log files using streaming chunk iteration,
deterministic multiline parsing via SuperOfficeWarningLogParser, strict scan bounds,
trusted source timezone normalization with DST ambiguity and gap validation,
and fail-safe handling.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC
from enum import Enum
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from diag_mcp.adapters.app_log_locator import (
    WarningLogCandidateLocator,
)
from diag_mcp.adapters.app_log_resolver import (
    ApplicationLogLocationResolver,
)
from diag_mcp.adapters.warning_log_parser import (
    ParsedWarningEvent,
    SuperOfficeWarningLogParser,
)
from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    LogRecordDomainDTO,
    LogSearchCriteriaDTO,
)
from diag_mcp.contracts.errors import LogSearchError
from diag_mcp.contracts.interfaces import LogSearchClient
from diag_mcp.settings import DiagnosticsServerSettings

if TYPE_CHECKING:
    from collections.abc import Generator
    from datetime import datetime
    from pathlib import Path

    from diag_mcp.adapters.app_log_locator import WarningLogCandidateBatch

SERVICE_NAME = "superoffice_cs"
MAX_RESULT_LIMIT_BOUND = 50
DEFAULT_RESULT_LIMIT = 20


class LocalTimestampClassification(Enum):
    """Classification of a naive local wall-clock timestamp under a target timezone."""

    VALID = "VALID"
    AMBIGUOUS = "AMBIGUOUS"
    NONEXISTENT = "NONEXISTENT"


def classify_local_timestamp(
    local_dt: datetime,
    source_tz: ZoneInfo,
) -> tuple[LocalTimestampClassification, datetime | None]:
    """Classify a naive local wall-clock timestamp via deterministic round-trip validation.

    Evaluates both fold=0 and fold=1 candidates under the configured source timezone:
    - If neither candidate round-trips to local_dt, time is in spring gap (NONEXISTENT).
    - If both round-trip to local_dt but map to different UTC instants, time is (AMBIGUOUS).
    - If unambiguous, returns VALID with the confirmed UTC instant.
    """
    cand0 = local_dt.replace(tzinfo=source_tz, fold=0)
    cand1 = local_dt.replace(tzinfo=source_tz, fold=1)

    utc0 = cand0.astimezone(UTC)
    utc1 = cand1.astimezone(UTC)

    back0 = utc0.astimezone(source_tz).replace(tzinfo=None)
    back1 = utc1.astimezone(source_tz).replace(tzinfo=None)

    # Nonexistent check: neither candidate round-trips to the input wall-clock
    if local_dt not in (back0, back1):
        return LocalTimestampClassification.NONEXISTENT, None

    # Ambiguous check: both round-trip to the input wall-clock, but map to different UTC instants
    if utc0 != utc1:
        return LocalTimestampClassification.AMBIGUOUS, None

    return LocalTimestampClassification.VALID, utc0


def _stream_lines(
    file_path: Path,
    chunk_size: int,
    max_bytes: int,
) -> Generator[str, None, int]:
    """Yield complete lines from file up to max_bytes, handling optional UTF-8 BOM."""
    bytes_read = 0
    buffer = b""
    is_first_chunk = True

    with file_path.open("rb") as f:
        while True:
            remaining_bytes = max_bytes - bytes_read
            if remaining_bytes <= 0:
                break
            read_size = min(chunk_size, remaining_bytes)
            chunk = f.read(read_size)
            if not chunk:
                break
            bytes_read += len(chunk)

            if is_first_chunk:
                is_first_chunk = False
                if chunk.startswith(b"\xef\xbb\xbf"):
                    chunk = chunk[3:]

            buffer += chunk
            while b"\n" in buffer:
                line_bytes, buffer = buffer.split(b"\n", 1)
                yield line_bytes.decode("utf-8")

        if buffer:
            yield buffer.decode("utf-8")

    return bytes_read


class SuperOfficeWarningLogReader(LogSearchClient):
    """Streaming reader for SuperOffice warning log files.

    Enforces physical scan bounds: max files, max scan bytes, scan timeout,
    and event line/byte limits. Normalizes timezone-less timestamps to UTC using
    trusted deployment timezone configuration with strict DST safety (fails closed
    if timezone is unconfigured, ambiguous, or nonexistent).
    """

    def __init__(
        self,
        settings: DiagnosticsServerSettings | None = None,
        *,
        locator: WarningLogCandidateLocator | None = None,
        location_resolver: ApplicationLogLocationResolver | None = None,
        log_dir: Path | None = None,
        filename_prefix: str = "warning",
        enabled: bool | None = None,
        max_files: int | None = None,
        max_scan_bytes: int | None = None,
        scan_timeout_seconds: float | None = None,
        max_event_lines: int | None = None,
        max_event_bytes: int | None = None,
        read_chunk_bytes: int | None = None,
        application_log_timezone: str | None = None,
    ) -> None:
        cfg = settings or DiagnosticsServerSettings()

        self._enabled = enabled if enabled is not None else cfg.application_log_enabled
        self._max_files = max_files if max_files is not None else cfg.application_max_files
        self._max_scan_bytes = (
            max_scan_bytes if max_scan_bytes is not None else cfg.application_max_scan_bytes
        )
        self._scan_timeout_seconds = (
            scan_timeout_seconds
            if scan_timeout_seconds is not None
            else cfg.application_scan_timeout_seconds
        )
        self._max_event_lines = (
            max_event_lines if max_event_lines is not None else cfg.application_max_event_lines
        )
        self._max_event_bytes = (
            max_event_bytes if max_event_bytes is not None else cfg.application_max_event_bytes
        )
        self._read_chunk_bytes = (
            read_chunk_bytes if read_chunk_bytes is not None else cfg.application_read_chunk_bytes
        )
        self._application_log_timezone = (
            application_log_timezone
            if application_log_timezone is not None
            else cfg.application_log_timezone
        )

        self._locator = locator or WarningLogCandidateLocator(
            settings=cfg,
            max_files=self._max_files,
        )
        self._resolver = location_resolver
        self._override_log_dir = log_dir
        self._filename_prefix = filename_prefix
        self._override_path_setting = cfg.application_log_path_override

    def get_source_timezone(self) -> ZoneInfo:
        """Resolve and validate the configured source timezone for warning log timestamps.

        Raises:
            LogSearchError: If application_log_timezone is unconfigured or invalid.
        """
        tz_name = self._application_log_timezone
        if tz_name is None or not tz_name.strip():
            raise LogSearchError(
                message=(
                    "SuperOffice warning log timezone is not configured. "
                    "Set DIAGNOSTICS_APPLICATION_LOG_TIMEZONE before enabling log search."
                ),
                error_code="APPLICATION_LOG_TIMEZONE_NOT_CONFIGURED",
            )

        try:
            return ZoneInfo(tz_name.strip())
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise LogSearchError(
                message=f"Configured SuperOffice warning log timezone '{tz_name}' is invalid.",
                error_code="APPLICATION_LOG_TIMEZONE_INVALID",
            ) from exc

    @classmethod
    def classify_local_timestamp(
        cls,
        local_dt: datetime,
        source_tz: ZoneInfo,
    ) -> tuple[LocalTimestampClassification, datetime | None]:
        """Classify a local wall-clock timestamp under source timezone."""
        return classify_local_timestamp(local_dt, source_tz)

    @classmethod
    def normalize_timestamp(cls, local_dt: datetime, source_tz: ZoneInfo) -> datetime:
        """Convert a naive local wall-clock timestamp to an aware UTC timestamp.

        Enforces deterministic round-trip validation. Fails safe if the local timestamp
        is ambiguous (fall-back duplicate) or nonexistent (spring-forward gap).

        Raises:
            LogSearchError:
                - APPLICATION_LOG_TIMESTAMP_AMBIGUOUS if local time is ambiguous.
                - APPLICATION_LOG_TIMESTAMP_NONEXISTENT if local time never occurred.
        """
        classification, utc_dt = cls.classify_local_timestamp(local_dt, source_tz)
        if classification == LocalTimestampClassification.AMBIGUOUS:
            raise LogSearchError(
                message="SuperOffice warning log timestamp is ambiguous during DST transition.",
                error_code="APPLICATION_LOG_TIMESTAMP_AMBIGUOUS",
            )
        if classification == LocalTimestampClassification.NONEXISTENT:
            raise LogSearchError(
                message="SuperOffice warning log timestamp does not exist during DST transition.",
                error_code="APPLICATION_LOG_TIMESTAMP_NONEXISTENT",
            )
        assert utc_dt is not None
        return utc_dt

    def read_events_from_file(
        self,
        file_path: Path,
        *,
        max_bytes: int | None = None,
    ) -> list[ParsedWarningEvent]:
        """Synchronously read and parse all warning events from a single file."""
        limit_bytes = max_bytes if max_bytes is not None else self._max_scan_bytes
        parser = SuperOfficeWarningLogParser(
            max_event_lines=self._max_event_lines,
            max_event_bytes=self._max_event_bytes,
        )
        events: list[ParsedWarningEvent] = []

        try:
            line_generator = _stream_lines(
                file_path=file_path,
                chunk_size=self._read_chunk_bytes,
                max_bytes=limit_bytes,
            )
            for line in line_generator:
                completed = parser.feed_line(line)
                if completed is not None:
                    events.append(completed)

            final_event = parser.end_of_file()
            if final_event is not None:
                events.append(final_event)

        except UnicodeDecodeError as exc:
            raise LogSearchError(
                message="SuperOffice warning log contains invalid UTF-8 encoding.",
                error_code="APPLICATION_LOG_ENCODING_ERROR",
            ) from exc

        return events

    async def _resolve_candidates(self) -> WarningLogCandidateBatch:
        """Resolve candidate files based on direct override, resolver, or settings."""
        if self._override_log_dir is not None:
            return self._locator.locate_candidates(
                parent_directory=self._override_log_dir,
                filename_prefix=self._filename_prefix,
            )

        if self._resolver is not None:
            loc = await self._resolver.resolve_location()
            return self._locator.locate_from_location(loc)

        if self._override_path_setting:
            parent_dir, prefix, _ = ApplicationLogLocationResolver.parse_path_prefix(
                self._override_path_setting
            )
            return self._locator.locate_candidates(
                parent_directory=parent_dir,
                filename_prefix=prefix,
            )

        raise LogSearchError(
            message="No resolver, directory override, or path setting provided.",
            error_code="APPLICATION_LOG_LOCATION_UNRESOLVED",
        )

    def _process_candidate_events(
        self,
        candidate_path: Path,
        remaining_bytes: int,
        *,
        criteria: LogSearchCriteriaDTO,
        effective_limit: int,
        current_count: int,
        start_monotonic: float,
        source_tz: ZoneInfo,
    ) -> tuple[list[LogRecordDomainDTO], bool]:
        """Read and filter events from a candidate file within remaining bounds."""
        records: list[LogRecordDomainDTO] = []
        is_truncated = False

        events = self.read_events_from_file(candidate_path, max_bytes=remaining_bytes)

        for event in events:
            if time.monotonic() - start_monotonic >= self._scan_timeout_seconds:
                is_truncated = True
                break

            if not self._matches_criteria(event, criteria, source_tz):
                continue

            records.append(self.to_domain_dto(event, source_tz))
            if current_count + len(records) >= effective_limit:
                is_truncated = True
                break

        return records, is_truncated

    async def search_logs(
        self, criteria: LogSearchCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[LogRecordDomainDTO]:
        """Search application warning logs matching structured filter criteria."""
        start_monotonic = time.monotonic()

        if not self._enabled:
            raise LogSearchError(
                message="SuperOffice warning log backend is disabled by configuration.",
                error_code="APPLICATION_LOG_NOT_ENABLED",
            )

        # Fail-closed if timezone is unconfigured or invalid up front
        source_tz = self.get_source_timezone()

        effective_limit = min(
            criteria.limit if criteria.limit is not None else DEFAULT_RESULT_LIMIT,
            MAX_RESULT_LIMIT_BOUND,
        )

        candidate_batch = await self._resolve_candidates()
        records: list[LogRecordDomainDTO] = []
        is_truncated = False
        total_bytes_scanned = 0

        for candidate in candidate_batch.candidates:
            if len(records) >= effective_limit:
                is_truncated = True
                break

            remaining_bytes = self._max_scan_bytes - total_bytes_scanned
            elapsed = time.monotonic() - start_monotonic
            if remaining_bytes <= 0 or elapsed >= self._scan_timeout_seconds:
                is_truncated = True
                break

            try:
                file_records, file_truncated = self._process_candidate_events(
                    candidate.file_path,
                    remaining_bytes,
                    criteria=criteria,
                    effective_limit=effective_limit,
                    current_count=len(records),
                    start_monotonic=start_monotonic,
                    source_tz=source_tz,
                )
                records.extend(file_records)

                file_size = candidate.size_bytes
                total_bytes_scanned += min(file_size, remaining_bytes)
                if (
                    file_truncated
                    or file_size > remaining_bytes
                    or total_bytes_scanned >= self._max_scan_bytes
                    or (time.monotonic() - start_monotonic) >= self._scan_timeout_seconds
                ):
                    is_truncated = True
                    break

            except LogSearchError:
                raise
            except OSError as exc:
                raise LogSearchError(
                    message="Failed to read SuperOffice warning log candidate file.",
                    error_code="APPLICATION_LOG_READ_FAILED",
                ) from exc

        return BoundedDiagnosticResultDTO[LogRecordDomainDTO](
            items=tuple(records),
            returned_count=len(records),
            is_truncated=is_truncated,
        )

    def _matches_criteria(
        self,
        event: ParsedWarningEvent,
        criteria: LogSearchCriteriaDTO,
        source_tz: ZoneInfo,
    ) -> bool:
        """Evaluate whether a parsed event satisfies search criteria."""
        event_utc = self.normalize_timestamp(event.local_timestamp, source_tz)

        if criteria.start_time is not None and event_utc < criteria.start_time:
            return False
        if criteria.end_time is not None and event_utc > criteria.end_time:
            return False

        if criteria.service_name is not None and criteria.service_name.lower() not in (
            SERVICE_NAME,
            "superoffice_warning",
        ):
            return False

        if criteria.severity is not None and criteria.severity.upper() != "WARN":
            return False

        if criteria.query_text:
            query_lower = criteria.query_text.lower()
            if query_lower not in event.full_message.lower():
                return False

        return True

    def to_domain_dto(
        self,
        event: ParsedWarningEvent,
        source_tz: ZoneInfo | None = None,
    ) -> LogRecordDomainDTO:
        """Map parsed warning event to canonical LogRecordDomainDTO.

        Narrow source normalization boundary:
        - Timestamp: local naive timestamp is converted to aware UTC using the
          explicitly configured source timezone (ZoneInfo) via astimezone(UTC).
          Fails safe if the timestamp is ambiguous or nonexistent during DST transitions.
        - Severity: 'WARN' derived from source stream (source-derived severity).
        - Neutral identifiers: numeric_id stored in raw_context, no thread_id assumption.
        """
        tz = source_tz or self.get_source_timezone()
        normalized_utc = self.normalize_timestamp(event.local_timestamp, tz)

        id_payload = (
            f"{normalized_utc.isoformat()}|{event.numeric_id}|"
            f"{event.process_name}|{event.metric_1}|{event.metric_2}|{event.header_message[:64]}"
        )
        log_id = f"warn-{hashlib.sha256(id_payload.encode('utf-8')).hexdigest()[:16]}"

        raw_context: dict[str, str] = {
            "numeric_id": str(event.numeric_id),
            "context": event.context,
            "process_name": event.process_name,
            "metric_1": str(event.metric_1),
            "metric_2": str(event.metric_2),
            "physical_line_count": str(event.physical_line_count),
            "is_truncated": str(event.is_truncated),
        }
        if event.component:
            raw_context["component"] = event.component
        if event.method:
            raw_context["method"] = event.method

        return LogRecordDomainDTO(
            log_id=log_id,
            timestamp=normalized_utc,
            service_name=SERVICE_NAME,
            severity="WARN",
            message=event.full_message,
            correlation_id=None,
            ticket_id=None,
            raw_context=raw_context,
        )
