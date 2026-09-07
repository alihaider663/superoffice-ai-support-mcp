"""Collectors sub-package for Layer-4 investigation evidence adapters."""

from platform_investigation_service.collectors.diagnostics_collector import (
    DiagnosticsEvidenceCollector,
)
from platform_investigation_service.collectors.knowledge_collector import (
    KnowledgeEvidenceCollector,
)
from platform_investigation_service.collectors.logs_collector import (
    DiagnosticLogsEvidenceCollector,
    LogsEvidenceCollector,
)
from platform_investigation_service.collectors.superoffice_collector import (
    SuperOfficeEvidenceCollector,
)

__all__ = [
    "DiagnosticLogsEvidenceCollector",
    "DiagnosticsEvidenceCollector",
    "KnowledgeEvidenceCollector",
    "LogsEvidenceCollector",
    "SuperOfficeEvidenceCollector",
]
