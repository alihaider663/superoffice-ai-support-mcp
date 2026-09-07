"""Diagnostics contract definitions, DTOs, errors, and protocol interfaces."""

from diag_mcp.contracts.dtos import (
    BlockingSessionCriteriaDTO,
    BlockingSessionDomainDTO,
    BoundedDiagnosticResultDTO,
    DatabaseHealthDomainDTO,
    DeadlockCriteriaDTO,
    DeadlockDomainDTO,
    LogRecordDomainDTO,
    LogSearchCriteriaDTO,
    SanitizedLogExcerptDTO,
    SlowQueryCriteriaDTO,
    SlowQueryDomainDTO,
    TicketDiagnosticCriteriaDTO,
    TicketDiagnosticRecordDomainDTO,
)
from diag_mcp.contracts.errors import (
    DatabaseDiagnosticError,
    LogSearchError,
)
from diag_mcp.contracts.interfaces import (
    DiagnosticRepository,
    LogSearchClient,
)

__all__ = [
    "BlockingSessionCriteriaDTO",
    "BlockingSessionDomainDTO",
    "BoundedDiagnosticResultDTO",
    "DatabaseDiagnosticError",
    "DatabaseHealthDomainDTO",
    "DeadlockCriteriaDTO",
    "DeadlockDomainDTO",
    "DiagnosticRepository",
    "LogRecordDomainDTO",
    "LogSearchClient",
    "LogSearchCriteriaDTO",
    "LogSearchError",
    "SanitizedLogExcerptDTO",
    "SlowQueryCriteriaDTO",
    "SlowQueryDomainDTO",
    "TicketDiagnosticCriteriaDTO",
    "TicketDiagnosticRecordDomainDTO",
]
