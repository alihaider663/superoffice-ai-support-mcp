"""Deterministic in-memory FakeKnowledgeRepository for offline contract testing."""

from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnowledgeSearchResultDomainDTO,
    KnownIssueDomainDTO,
    KnownIssueSearchCriteriaDTO,
    RunbookDetailDomainDTO,
)
from kb_mcp.contracts.errors import (
    KnowledgeSearchError,
    RunbookNotFoundError,
)


class FakeKnowledgeRepository:
    """Deterministic in-memory implementation of KnowledgeRepository Protocol."""

    def __init__(self) -> None:
        self._documents: list[KnowledgeSearchResultDomainDTO] = []
        self._runbooks: dict[str, RunbookDetailDomainDTO] = {}
        self._known_issues: list[KnownIssueDomainDTO] = []
        self._should_fail: bool = False

    # Seed helpers for test setup
    def seed_document(self, doc: KnowledgeSearchResultDomainDTO) -> None:
        """Seed a knowledge document into the fake store."""
        self._documents.append(doc)

    def seed_runbook(self, runbook: RunbookDetailDomainDTO) -> None:
        """Seed a runbook into the fake store."""
        self._runbooks[runbook.runbook_id] = runbook

    def seed_known_issue(self, issue: KnownIssueDomainDTO) -> None:
        """Seed a known issue into the fake store."""
        self._known_issues.append(issue)

    def set_should_fail(self, should_fail: bool) -> None:
        """Simulate a knowledge repository failure."""
        self._should_fail = should_fail

    # Protocol implementation
    async def search_knowledge(
        self, criteria: KnowledgeSearchCriteriaDTO
    ) -> tuple[KnowledgeSearchResultDomainDTO, ...]:
        """Search knowledge documents with in-memory filtering and deterministic ranking."""
        if self._should_fail:
            raise KnowledgeSearchError("Simulated knowledge store query failure.")

        query_terms = [t.lower() for t in criteria.query_text.split() if t]
        matched: list[KnowledgeSearchResultDomainDTO] = []

        for doc in self._documents:
            # Category filter
            if criteria.category and doc.category.lower() != criteria.category.lower():
                continue
            # Product filter
            if criteria.product and (doc.product or "").lower() != criteria.product.lower():
                continue
            # Version filter
            if criteria.version and (doc.version or "").lower() != criteria.version.lower():
                continue
            # Tags filter
            if criteria.tags:
                doc_tags_lower = {t.lower() for t in doc.tags}
                if not any(req_tag.lower() in doc_tags_lower for req_tag in criteria.tags):
                    continue

            # Query match check (title, content, tags)
            doc_text = f"{doc.title} {doc.content_excerpt} {' '.join(doc.tags)}".lower()
            if query_terms and not any(term in doc_text for term in query_terms):
                continue

            # Relevance threshold filter
            if (
                criteria.min_relevance_score is not None
                and doc.relevance_score < criteria.min_relevance_score
            ):
                continue

            matched.append(doc)

        # Sort descending by relevance score for deterministic ranking
        matched.sort(key=lambda d: d.relevance_score, reverse=True)

        return tuple(matched[: criteria.limit])

    async def get_runbook(self, runbook_id: str) -> RunbookDetailDomainDTO:
        """Fetch runbook by ID or raise RunbookNotFoundError."""
        if self._should_fail:
            raise KnowledgeSearchError("Simulated runbook retrieval failure.")

        if runbook_id not in self._runbooks:
            raise RunbookNotFoundError(runbook_id)

        return self._runbooks[runbook_id]

    async def find_known_issues(
        self, criteria: KnownIssueSearchCriteriaDTO
    ) -> tuple[KnownIssueDomainDTO, ...]:
        """Search known issues with in-memory filtering."""
        if self._should_fail:
            raise KnowledgeSearchError("Simulated known issues query failure.")

        matched: list[KnownIssueDomainDTO] = []
        for issue in self._known_issues:
            if criteria.category and issue.category.lower() != criteria.category.lower():
                continue
            if criteria.product and not any(
                criteria.product.lower() in p.lower() for p in issue.affected_products
            ):
                continue
            if criteria.version and not any(
                criteria.version.lower() in v.lower() for v in issue.affected_versions
            ):
                continue
            if criteria.query_text:
                q = criteria.query_text.lower()
                text = f"{issue.title} {issue.symptom_summary} {issue.root_cause_summary}".lower()
                if q not in text:
                    continue

            matched.append(issue)

        return tuple(matched[: criteria.limit])
