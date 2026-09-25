"""Knowledge base evidence collector adapter.

Consumes KnowledgeServicePort to retrieve matching known issues, workarounds,
and runbook/documentation chunks from pgvector/PostgreSQL knowledge store.

Implements OutcomeAwareEvidenceCollector protocol for registration
with EvidenceAggregatorEngine.

Import policy: NO server runtime/adapter imports. Uses port protocol and contract DTOs only.
"""

from datetime import UTC, datetime

from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnownIssueSearchCriteriaDTO,
)
from platform_investigation.models import (
    CorrelationReference,
    DiagnosticEvidence,
    EvidenceSourceType,
    SourceCollectionResult,
    SourceCollectionStatus,
)
from platform_investigation_service.models import KnowledgeSelectionDTO
from platform_investigation_service.ports import KnowledgeServicePort
from platform_observability.logging import get_logger

logger = get_logger(__name__)


class KnowledgeEvidenceCollector:
    """Concrete OutcomeAwareEvidenceCollector for Knowledge Base & Runbooks.

    When KnowledgeServicePort is provided and query context is available:
    - Queries verified known issues and solution workarounds.
    - Queries relevant knowledge base documentation and runbooks.
    - Transforms findings into sanitized DiagnosticEvidence items.

    If KnowledgeServicePort is unconfigured or returns backend unconfigured:
    - Returns NOT_CONFIGURED status deterministically (BLK-2B4-01 fallback).
    """

    def __init__(
        self,
        service: KnowledgeServicePort | None = None,
        *,
        selection: KnowledgeSelectionDTO | None = None,
        query_context: str | None = None,
    ) -> None:
        self._service = service
        self._selection = selection or KnowledgeSelectionDTO()
        self._query_context = query_context

    @property
    def source_type(self) -> EvidenceSourceType:
        """System origin identifier for this collector."""
        return EvidenceSourceType.KNOWLEDGE_BASE

    async def collect(
        self,
        investigation_id: str,
        correlation_key: str,
    ) -> SourceCollectionResult:
        """Collect knowledge base and known issue evidence."""
        _ = investigation_id

        if not self._selection.include_knowledge_search:
            logger.info("Knowledge collector skipped: search not requested")
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.SUCCESS,
                evidence=(),
            )

        if self._service is None:
            logger.info("Knowledge collector: service not configured (fallback NOT_CONFIGURED)")
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.NOT_CONFIGURED,
                evidence=(),
                error_code="KNOWLEDGE_BASE_NOT_CONFIGURED",
                error_message="Knowledge store backend is not configured.",
            )

        search_query = (
            self._selection.query_override or self._query_context or correlation_key
        ).strip()

        if len(search_query) < 2:
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.SUCCESS,
                evidence=(),
            )

        # Truncate query safely to 256 chars
        clean_query = search_query[:256]
        now = datetime.now(UTC)
        evidence_items: list[DiagnosticEvidence] = []

        try:
            # 1. Search known issues
            issue_criteria = KnownIssueSearchCriteriaDTO(
                query_text=clean_query,
                limit=self._selection.limit,
            )
            issues = await self._service.find_known_issues(issue_criteria)

            for issue in issues:
                evidence_items.append(
                    DiagnosticEvidence(
                        evidence_id=f"kb:issue:{issue.issue_id}",
                        source_type=self.source_type,
                        title="Knowledge Base verified known issue",
                        timestamp=now,
                        data={
                            "issue_id": issue.issue_id,
                            "title": issue.title,
                            "symptom_summary": issue.symptom_summary,
                            "root_cause_summary": issue.root_cause_summary,
                            "workaround": issue.workaround,
                            "permanent_fix_reference": issue.permanent_fix_reference,
                            "affected_products": list(issue.affected_products),
                        },
                        tags=("knowledge", "known_issue"),
                        correlation_references=(
                            CorrelationReference(
                                namespace="known_issue",
                                value=issue.issue_id,
                            ),
                        ),
                    )
                )

            # 2. If known issues didn't saturate limit, supplement with semantic chunks
            remaining_limit = self._selection.limit - len(evidence_items)
            if remaining_limit > 0:
                chunk_criteria = KnowledgeSearchCriteriaDTO(
                    query_text=clean_query,
                    limit=remaining_limit,
                )
                chunks = await self._service.search_knowledge(chunk_criteria)
                for chunk in chunks:
                    evidence_items.append(
                        DiagnosticEvidence(
                            evidence_id=f"kb:doc:{chunk.document_id}",
                            source_type=self.source_type,
                            title="Knowledge Base article observation",
                            timestamp=now,
                            data={
                                "document_id": chunk.document_id,
                                "title": chunk.title,
                                "content_excerpt": chunk.content_excerpt,
                                "category": chunk.category,
                                "relevance_score": chunk.relevance_score,
                                "source_reference": chunk.source_reference,
                            },
                            tags=("knowledge", "article"),
                            correlation_references=(
                                CorrelationReference(
                                    namespace="doc_ref",
                                    value=chunk.source_reference,
                                ),
                            ),
                        )
                    )

        except Exception as exc:
            err_name = type(exc).__name__
            err_str = str(exc).upper()
            is_unconfigured = (
                "NOTCONFIGURED" in err_name.upper()
                or "NOT_CONFIGURED" in err_str
                or "UNCONFIGURED" in err_str
            )
            if is_unconfigured:
                logger.info("Knowledge collector: backend unconfigured exception")
                return SourceCollectionResult(
                    source_type=self.source_type,
                    status=SourceCollectionStatus.NOT_CONFIGURED,
                    evidence=(),
                    error_code="KNOWLEDGE_BASE_NOT_CONFIGURED",
                    error_message="Knowledge store backend is not configured.",
                )

            logger.error(
                "Knowledge base retrieval failed",
                error_code="KNOWLEDGE_BASE_RETRIEVAL_FAILED",
                error=str(exc),
            )
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.FAILED,
                evidence=(),
                error_code="KNOWLEDGE_BASE_RETRIEVAL_FAILED",
                error_message="An unexpected error occurred searching the knowledge base.",
            )

        logger.info(
            "Knowledge evidence collected",
            evidence_count=len(evidence_items),
        )

        return SourceCollectionResult(
            source_type=self.source_type,
            status=SourceCollectionStatus.SUCCESS,
            evidence=tuple(evidence_items),
            collected_at=now,
        )
