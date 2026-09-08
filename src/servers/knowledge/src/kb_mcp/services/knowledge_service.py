"""Knowledge Application Service coordinating knowledge retrieval, runbooks, and sanitization."""

from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnownIssueSearchCriteriaDTO,
    MinimizedKnowledgeChunkDTO,
    MinimizedKnownIssueDTO,
    MinimizedRunbookDTO,
)
from kb_mcp.contracts.errors import KnowledgeSearchError
from kb_mcp.contracts.interfaces import EmbeddingProvider, KnowledgeRepository
from platform_security.sanitization import RecursiveOutputSanitizer


class KnowledgeApplicationService:
    """Application Service orchestrating Knowledge retrieval and AI-facing output minimization."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        sanitizer: RecursiveOutputSanitizer | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._repository = repository
        self._sanitizer = sanitizer or RecursiveOutputSanitizer()
        self._embedding_provider = embedding_provider

    def _sanitize_string(self, text: str | None) -> str:
        """Sanitize a free-text string using RecursiveOutputSanitizer."""
        if not text:
            return ""
        result = self._sanitizer.pii_filter.redact(text)
        return result.sanitized_text

    async def search_knowledge(
        self, criteria: KnowledgeSearchCriteriaDTO
    ) -> tuple[MinimizedKnowledgeChunkDTO, ...]:
        """Perform semantic search across knowledge base and project AI-safe minimized chunks."""
        if self._embedding_provider is not None:
            query_embedding = await self._embedding_provider.embed_query(criteria.query_text)
            domain_results = await self._repository.search_knowledge(criteria, query_embedding)
        else:
            try:
                domain_results = await self._repository.search_knowledge(criteria)  # type: ignore[call-arg]
            except TypeError as err:
                raise KnowledgeSearchError(
                    message="Embedding provider is required for semantic knowledge search.",
                    error_code="EMBEDDING_PROVIDER_REQUIRED",
                ) from err

        minimized_chunks: list[MinimizedKnowledgeChunkDTO] = []
        for doc in domain_results:
            minimized_chunks.append(
                MinimizedKnowledgeChunkDTO(
                    document_id=doc.document_id,
                    title=self._sanitize_string(doc.title),
                    content_excerpt=self._sanitize_string(doc.content_excerpt),
                    category=doc.category,
                    relevance_score=doc.relevance_score,
                    source_reference=doc.source_reference,
                )
            )

        return tuple(minimized_chunks)

    async def get_runbook(self, runbook_id: str) -> MinimizedRunbookDTO:
        """Fetch operational runbook and project AI-safe minimized summary."""
        rb = await self._repository.get_runbook(runbook_id)

        sanitized_diag = tuple(self._sanitize_string(step) for step in rb.diagnostic_steps if step)
        sanitized_remed = tuple(
            self._sanitize_string(step) for step in rb.remediation_steps if step
        )

        return MinimizedRunbookDTO(
            runbook_id=rb.runbook_id,
            title=self._sanitize_string(rb.title),
            problem_description=self._sanitize_string(rb.problem_description),
            diagnostic_steps=sanitized_diag,
            remediation_steps=sanitized_remed,
            source_reference=rb.source_reference,
        )

    async def find_known_issues(
        self, criteria: KnownIssueSearchCriteriaDTO
    ) -> tuple[MinimizedKnownIssueDTO, ...]:
        """Query verified known issues and project AI-safe minimized summaries."""
        domain_issues = await self._repository.find_known_issues(criteria)

        minimized_issues: list[MinimizedKnownIssueDTO] = []
        for issue in domain_issues:
            workaround = (
                self._sanitize_string(issue.workaround) if issue.workaround is not None else None
            )
            minimized_issues.append(
                MinimizedKnownIssueDTO(
                    issue_id=issue.issue_id,
                    title=self._sanitize_string(issue.title),
                    symptom_summary=self._sanitize_string(issue.symptom_summary),
                    workaround=workaround,
                    source_reference=issue.source_reference,
                )
            )

        return tuple(minimized_issues)
