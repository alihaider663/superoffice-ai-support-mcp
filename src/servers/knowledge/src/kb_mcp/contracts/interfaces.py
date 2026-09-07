"""Protocol interfaces for Knowledge repository and retrieval boundaries."""

from typing import Protocol, runtime_checkable

from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnowledgeSearchResultDomainDTO,
    KnownIssueDomainDTO,
    KnownIssueSearchCriteriaDTO,
    RunbookDetailDomainDTO,
)


@runtime_checkable
class KnowledgeRepository(Protocol):
    """Protocol for Supabase / pgvector semantic knowledge retrieval repository."""

    async def search_knowledge(
        self, criteria: KnowledgeSearchCriteriaDTO
    ) -> tuple[KnowledgeSearchResultDomainDTO, ...]:
        """Perform semantic search across approved product and troubleshooting documentation.

        Raises:
            KnowledgeSearchError: If the underlying vector store query fails.
        """
        ...

    async def get_runbook(self, runbook_id: str) -> RunbookDetailDomainDTO:
        """Fetch a specific operational runbook or guide by its identifier.

        Raises:
            RunbookNotFoundError: If no runbook with the given ID exists.
            KnowledgeSearchError: If communication with the knowledge store fails.
        """
        ...

    async def find_known_issues(
        self, criteria: KnownIssueSearchCriteriaDTO
    ) -> tuple[KnownIssueDomainDTO, ...]:
        """Query verified known issues matching symptom keywords and product context.

        Raises:
            KnowledgeSearchError: If knowledge store lookup fails.
        """
        ...
