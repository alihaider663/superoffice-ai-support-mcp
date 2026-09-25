"""Application logs evidence collector adapter.

Consumes LogsServicePort or DiagnosticsServicePort to search sanitized application
and API log excerpts matching incident correlation keys or search queries.

Implements OutcomeAwareEvidenceCollector protocol for registration
with EvidenceAggregatorEngine.

Import policy: NO server runtime/adapter imports. Uses port protocol and contract DTOs only.
"""

from datetime import UTC, datetime

from platform_investigation.models import (
    CorrelationReference,
    DiagnosticEvidence,
    EvidenceSourceType,
    SourceCollectionResult,
    SourceCollectionStatus,
)
from platform_investigation_service.models import LogsSelectionDTO
from platform_investigation_service.ports import LogsServicePort
from platform_observability.logging import get_logger

logger = get_logger(__name__)


class DiagnosticLogsEvidenceCollector:
    """Concrete OutcomeAwareEvidenceCollector for Application Logs.

    When LogsServicePort is provided and include_logs is enabled:
    - Queries sanitized log entries matching query or correlation context.
    - Transforms matching log excerpts into DiagnosticEvidence items.

    If LogsServicePort is unconfigured or logs are not requested:
    - Returns BLOCKED status deterministically (BLK-2B3-02 fallback).
    """

    def __init__(
        self,
        service: LogsServicePort | None = None,
        *,
        selection: LogsSelectionDTO | None = None,
        query_context: str | None = None,
    ) -> None:
        self._service = service
        self._selection = selection or LogsSelectionDTO()
        self._query_context = query_context

    @property
    def source_type(self) -> EvidenceSourceType:
        """System origin identifier for this collector."""
        return EvidenceSourceType.APPLICATION_LOGS

    async def collect(
        self,
        investigation_id: str,
        correlation_key: str,
    ) -> SourceCollectionResult:
        """Collect application log excerpts from logging service."""
        _ = investigation_id

        if not self._selection.include_logs:
            logger.info("Logs collector: not requested, returning BLOCKED fallback")
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.BLOCKED,
                evidence=(),
                error_code="DIAGNOSTIC_LOGS_BLOCKED",
                error_message="Application logging backend is blocked or not configured.",
            )

        if self._service is None:
            logger.info("Logs collector: service unconfigured, returning BLOCKED")
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.BLOCKED,
                evidence=(),
                error_code="DIAGNOSTIC_LOGS_BLOCKED",
                error_message="Application logging backend is blocked or not configured.",
            )

        search_query = (self._selection.query or self._query_context or correlation_key).strip()

        if not search_query:
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.SUCCESS,
                evidence=(),
            )

        clean_query = search_query[:256]
        now = datetime.now(UTC)

        try:
            log_result = await self._service.search_logs(
                query=clean_query,
                limit=self._selection.limit,
            )

            evidence_items: list[DiagnosticEvidence] = []
            for item in log_result.items:
                ts = item.timestamp if isinstance(item.timestamp, datetime) else now
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)

                refs: list[CorrelationReference] = []
                if item.correlation_id:
                    refs.append(
                        CorrelationReference(
                            namespace="correlation_id",
                            value=item.correlation_id,
                        )
                    )

                evidence_items.append(
                    DiagnosticEvidence(
                        evidence_id=f"log:{item.excerpt_id}",
                        source_type=self.source_type,
                        title="Application log observation",
                        timestamp=ts,
                        data={
                            "excerpt_id": item.excerpt_id,
                            "service_name": item.service_name,
                            "severity": item.severity,
                            "sanitized_message": item.sanitized_message,
                            "correlation_id": item.correlation_id,
                        },
                        tags=("diagnostics", "logs", "excerpt"),
                        correlation_references=tuple(refs),
                    )
                )

            logger.info(
                "Logs evidence collected",
                evidence_count=len(evidence_items),
            )

            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.SUCCESS,
                evidence=tuple(evidence_items),
                collected_at=now,
            )

        except Exception as exc:
            err_str = str(exc)
            if "NOT_CONFIGURED" in err_str or "unconfigured" in err_str.lower():
                logger.info("Logs collector backend unconfigured exception")
                return SourceCollectionResult(
                    source_type=self.source_type,
                    status=SourceCollectionStatus.BLOCKED,
                    evidence=(),
                    error_code="DIAGNOSTIC_LOGS_BLOCKED",
                    error_message="Application logging backend is blocked or not configured.",
                )

            logger.error(
                "Application log search failed",
                error_code="LOG_SEARCH_FAILED",
                error=err_str,
            )
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.FAILED,
                evidence=(),
                error_code="SOURCE_EXECUTION_FAILED",
                error_message="An unexpected error occurred during application log search.",
            )


# Backward-compatible alias
LogsEvidenceCollector = DiagnosticLogsEvidenceCollector
