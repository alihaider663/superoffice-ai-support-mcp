"""Platform Investigation Service - Layer-4 Application Service.

Composes generic Phase 3.1-3.4 investigation runtimes with domain-specific
evidence collectors to orchestrate single-request investigation cycles.
"""

from platform_investigation_service.collectors import (
    DiagnosticLogsEvidenceCollector,
    DiagnosticsEvidenceCollector,
    KnowledgeEvidenceCollector,
    LogsEvidenceCollector,
    SuperOfficeEvidenceCollector,
)
from platform_investigation_service.models import (
    DiagnosticsSelectionDTO,
    InvestigationRequest,
    InvestigationResult,
)
from platform_investigation_service.ports import (
    DiagnosticsServicePort,
    InvestigationOrchestratorPort,
    SuperOfficeServicePort,
)
from platform_investigation_service.service import InvestigationApplicationService

__all__ = [
    "DiagnosticLogsEvidenceCollector",
    "DiagnosticsEvidenceCollector",
    "DiagnosticsSelectionDTO",
    "DiagnosticsServicePort",
    "InvestigationApplicationService",
    "InvestigationOrchestratorPort",
    "InvestigationRequest",
    "InvestigationResult",
    "KnowledgeEvidenceCollector",
    "LogsEvidenceCollector",
    "SuperOfficeEvidenceCollector",
    "SuperOfficeServicePort",
]
