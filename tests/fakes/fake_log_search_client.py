"""Deterministic in-memory FakeLogSearchClient for offline contract testing."""

from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    LogRecordDomainDTO,
    LogSearchCriteriaDTO,
)
from diag_mcp.contracts.errors import LogSearchError


class FakeLogSearchClient:
    """Deterministic in-memory implementation of LogSearchClient Protocol."""

    def __init__(self) -> None:
        self._logs: list[LogRecordDomainDTO] = []
        self._should_fail: bool = False

    def seed_log(self, log: LogRecordDomainDTO) -> None:
        """Seed a log record into the fake search store."""
        self._logs.append(log)

    def set_should_fail(self, should_fail: bool) -> None:
        """Simulate a log search failure."""
        self._should_fail = should_fail

    async def search_logs(
        self, criteria: LogSearchCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[LogRecordDomainDTO]:
        """Search logs matching criteria with in-memory filtering."""
        if self._should_fail:
            raise LogSearchError("Simulated log search engine failure.")

        matched: list[LogRecordDomainDTO] = []
        for log in self._logs:
            if criteria.start_time and log.timestamp < criteria.start_time:
                continue
            if criteria.end_time and log.timestamp > criteria.end_time:
                continue
            if criteria.service_name and log.service_name.lower() != criteria.service_name.lower():
                continue
            if criteria.severity and log.severity.upper() != criteria.severity.upper():
                continue
            if (
                criteria.correlation_id
                and (log.correlation_id or "").lower() != criteria.correlation_id.lower()
            ):
                continue
            if criteria.ticket_id is not None and log.ticket_id != criteria.ticket_id:
                continue
            if criteria.query_text and criteria.query_text.lower() not in log.message.lower():
                continue

            matched.append(log)

        total_matched = len(matched)
        limit = criteria.limit if criteria.limit is not None else total_matched
        items_slice = tuple(matched[:limit])
        is_truncated = limit < total_matched

        return BoundedDiagnosticResultDTO[LogRecordDomainDTO](
            items=items_slice,
            returned_count=len(items_slice),
            total_matched=total_matched,
            is_truncated=is_truncated,
        )
