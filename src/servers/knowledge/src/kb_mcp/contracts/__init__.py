"""Knowledge contract definitions, DTOs, errors, constants, and protocol interfaces."""

from kb_mcp.contracts.constants import (
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_DIMENSION,
)
from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnowledgeSearchResultDomainDTO,
    KnownIssueDomainDTO,
    KnownIssueSearchCriteriaDTO,
    MinimizedKnowledgeChunkDTO,
    MinimizedKnownIssueDTO,
    MinimizedRunbookDTO,
    RunbookDetailDomainDTO,
)
from kb_mcp.contracts.errors import (
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingInferenceError,
    EmbeddingInputError,
    EmbeddingModelInitializationError,
    KnowledgeBackendNotConfiguredError,
    KnowledgeSearchError,
    MalformedRunbookDataError,
    RunbookNotFoundError,
)
from kb_mcp.contracts.interfaces import (
    EmbeddingProvider,
    KnowledgeRepository,
)

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "EMBEDDING_DIMENSION",
    "EmbeddingDimensionError",
    "EmbeddingError",
    "EmbeddingInferenceError",
    "EmbeddingInputError",
    "EmbeddingModelInitializationError",
    "EmbeddingProvider",
    "KnowledgeBackendNotConfiguredError",
    "KnowledgeRepository",
    "KnowledgeSearchCriteriaDTO",
    "KnowledgeSearchError",
    "KnowledgeSearchResultDomainDTO",
    "KnownIssueDomainDTO",
    "KnownIssueSearchCriteriaDTO",
    "MalformedRunbookDataError",
    "MinimizedKnowledgeChunkDTO",
    "MinimizedKnownIssueDTO",
    "MinimizedRunbookDTO",
    "RunbookDetailDomainDTO",
    "RunbookNotFoundError",
]
