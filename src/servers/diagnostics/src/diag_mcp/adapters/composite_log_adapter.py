"""Composite log search adapter coordinating enabled physical log readers (Gate 7A.4C-R1)."""

from __future__ import annotations

import logging

from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    LogRecordDomainDTO,
    LogSearchCriteriaDTO,
)
from diag_mcp.contracts.errors import LogSearchError
from diag_mcp.contracts.interfaces import LogSearchClient

logger = logging.getLogger(__name__)

MAX_RESULT_LIMIT_BOUND = 50
DEFAULT_RESULT_LIMIT = 20


class CompositeLogSearchAdapter(LogSearchClient):
    """Composite log search client querying enabled physical log readers.

    Sequentially queries enabled sources (IIS W3C, then SuperOffice warning logs),
    enforcing fail-closed semantics if no source is enabled, fail-closed semantics
    if an enabled source is unconfigured/unavailable, fail-safe semantics if any
    enabled source fails at runtime, and deterministic newest-first result merging.
    """

    def __init__(
        self,
        *,
        iis_reader: LogSearchClient | None = None,
        warning_reader: LogSearchClient | None = None,
        iis_enabled: bool = False,
        warning_enabled: bool = False,
    ) -> None:
        self._iis_reader = iis_reader
        self._warning_reader = warning_reader
        self._iis_enabled = iis_enabled
        self._warning_enabled = warning_enabled

    @property
    def has_enabled_sources(self) -> bool:
        """Return True if at least one configured log reader is enabled by admin."""
        return self._iis_enabled or self._warning_enabled

    @property
    def iis_enabled(self) -> bool:
        """Return configured admin intent for IIS log backend."""
        return self._iis_enabled

    @property
    def warning_enabled(self) -> bool:
        """Return configured admin intent for warning log backend."""
        return self._warning_enabled

    def _get_active_sources(self) -> list[tuple[str, LogSearchClient]]:
        """Validate configuration intent and return active source readers.

        Raises:
            LogSearchError: If no sources are enabled, or if an enabled source
                has no configured reader available (fail-closed semantics).
        """
        if not self._iis_enabled and not self._warning_enabled:
            raise LogSearchError(
                message="Log search runtime is not configured: no log backends are enabled.",
                error_code="LOG_SEARCH_BACKEND_NOT_CONFIGURED",
            )

        if self._iis_enabled and self._iis_reader is None:
            raise LogSearchError(
                message=(
                    "SuperOffice IIS log search is enabled "
                    "but backend is not configured or unavailable."
                ),
                error_code="IIS_LOG_BACKEND_NOT_CONFIGURED",
            )

        if self._warning_enabled and self._warning_reader is None:
            raise LogSearchError(
                message=(
                    "SuperOffice warning log search is enabled "
                    "but backend is not configured or unavailable."
                ),
                error_code="APPLICATION_LOG_BACKEND_NOT_CONFIGURED",
            )

        sources: list[tuple[str, LogSearchClient]] = []
        if self._iis_enabled:
            assert self._iis_reader is not None
            sources.append(("superoffice_iis", self._iis_reader))
        if self._warning_enabled:
            assert self._warning_reader is not None
            sources.append(("superoffice_cs", self._warning_reader))
        return sources

    async def search_logs(
        self, criteria: LogSearchCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[LogRecordDomainDTO]:
        """Query enabled log backends sequentially, merge, sort, and bound results."""
        active_sources = self._get_active_sources()

        raw_limit = criteria.limit if criteria.limit is not None else DEFAULT_RESULT_LIMIT
        effective_limit = min(max(1, raw_limit), MAX_RESULT_LIMIT_BOUND)
        source_criteria = criteria.model_copy(update={"limit": effective_limit})

        all_records: list[LogRecordDomainDTO] = []
        any_source_truncated = False
        all_totals_known = True
        total_sum = 0

        for source_id, reader in active_sources:
            try:
                res = await reader.search_logs(source_criteria)
            except LogSearchError:
                raise
            except Exception as exc:
                logger.exception("Log backend '%s' failed unexpectedly during search", source_id)
                raise LogSearchError(
                    message=f"Log search failed on backend '{source_id}'.",
                    error_code="LOG_SEARCH_BACKEND_FAILED",
                ) from exc

            if res.is_truncated:
                any_source_truncated = True
            if res.total_matched is None:
                all_totals_known = False
            else:
                total_sum += res.total_matched
            all_records.extend(res.items)

        # Deduplicate records by stable log_id
        deduped: list[LogRecordDomainDTO] = []
        seen_ids: set[str] = set()
        for r in all_records:
            if r.log_id not in seen_ids:
                seen_ids.add(r.log_id)
                deduped.append(r)

        # Deterministic newest-first sort: timestamp DESC, tie-breaker: service_name, log_id
        deduped.sort(
            key=lambda r: (r.timestamp, r.service_name, r.log_id),
            reverse=True,
        )

        final_truncated = any_source_truncated or (len(deduped) > effective_limit)
        final_items = tuple(deduped[:effective_limit])
        final_total = None if (any_source_truncated or not all_totals_known) else total_sum

        return BoundedDiagnosticResultDTO[LogRecordDomainDTO](
            items=final_items,
            returned_count=len(final_items),
            total_matched=final_total,
            is_truncated=final_truncated,
        )
