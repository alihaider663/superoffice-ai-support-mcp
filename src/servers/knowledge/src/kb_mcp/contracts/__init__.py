"""Knowledge contract definitions, DTOs, errors, and protocol interfaces."""

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
    KnowledgeBackendNotConfiguredError,
    KnowledgeSearchError,
    RunbookNotFoundError,
)
from kb_mcp.contracts.interfaces import (
    KnowledgeRepository,
)

__all__ = [
    "KnowledgeBackendNotConfiguredError",
    "KnowledgeRepository",
    "KnowledgeSearchCriteriaDTO",
    "KnowledgeSearchError",
    "KnowledgeSearchResultDomainDTO",
    "KnownIssueDomainDTO",
    "KnownIssueSearchCriteriaDTO",
    "MinimizedKnowledgeChunkDTO",
    "MinimizedKnownIssueDTO",
    "MinimizedRunbookDTO",
    "RunbookDetailDomainDTO",
    "RunbookNotFoundError",
]
