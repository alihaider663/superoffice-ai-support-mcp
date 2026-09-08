"""Protocol interfaces for Knowledge repository, retrieval, and embedding boundaries."""

from collections.abc import Sequence
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
        self,
        criteria: KnowledgeSearchCriteriaDTO,
        query_embedding: Sequence[float],
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


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for asynchronous text embedding generation."""

    async def embed_query(self, text: str) -> tuple[float, ...]:
        """Generate a dense vector embedding for a search query string.

        Args:
            text: Non-empty search query string.

        Returns:
            Tuple of floats representing the dense vector embedding (length 384).

        Raises:
            EmbeddingInputError: If query text is empty, whitespace-only, or invalid.
            EmbeddingInferenceError: If inference fails or produces non-finite values.
            EmbeddingDimensionError: If embedding dimension does not match 384.
        """
        ...

    async def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Generate dense vector embeddings for a sequence of document/chunk texts.

        Preserves input ordering. Empty input sequence returns ().

        Args:
            texts: Sequence of non-empty document strings.

        Returns:
            Tuple of embedding tuples, each of length 384.

        Raises:
            EmbeddingInputError: If any document is empty, whitespace-only, or invalid.
            EmbeddingInferenceError: If inference fails or count does not match.
            EmbeddingDimensionError: If any embedding dimension does not match 384.
        """
        ...
