"""Architecture boundary regression tests for Layer-4 investigation service.

Verifies that the Layer-4 platform_investigation_service package:
- Does NOT import any server runtime packages (so_mcp.services, diag_mcp.services, etc.)
- Does NOT import Gateway or RBAC modules
- Does NOT import database driver or external infrastructure libraries
- Proves InvestigationOrchestratorEngine satisfies InvestigationOrchestratorPort
- Proves Layer-3 InvestigationOrchestrator remains unchanged
- Properly exports expected public symbols
"""

from pathlib import Path

import platform_investigation_service
from platform_investigation.interfaces import InvestigationOrchestrator
from platform_investigation.orchestrator import InvestigationOrchestratorEngine
from platform_investigation_service.ports import InvestigationOrchestratorPort


def _get_service_package_dir() -> Path:
    """Locate the platform_investigation_service package source directory."""
    pkg_dir = (
        Path(__file__).parents[3]
        / "src"
        / "services"
        / "investigation"
        / "src"
        / "platform_investigation_service"
    )
    assert pkg_dir.exists(), f"Directory not found: {pkg_dir}"
    return pkg_dir


def test_layer4_has_no_forbidden_server_runtime_imports() -> None:
    """platform_investigation_service must not import server runtimes or infrastructure."""
    forbidden_modules = [
        "so_mcp.services",
        "so_mcp.adapters",
        "so_mcp.server",
        "diag_mcp.services",
        "diag_mcp.adapters",
        "diag_mcp.server",
        "kb_mcp",
        "infra_mcp",
        "platform_gateway",
        "sqlalchemy",
        "aioodbc",
        "supabase",
        "httpx",
        "respx",
        "mcp",
        "uvicorn",
        "starlette",
    ]

    pkg_dir = _get_service_package_dir()

    for py_file in pkg_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        relative = py_file.relative_to(pkg_dir)
        for forbidden in forbidden_modules:
            assert f"import {forbidden}" not in content, (
                f"Forbidden import '{forbidden}' found in {relative}"
            )
            assert f"from {forbidden}" not in content, (
                f"Forbidden from-import '{forbidden}' found in {relative}"
            )


def test_layer4_does_not_import_gateway_or_rbac() -> None:
    """Layer-4 service must not import Gateway, RBAC, or security routing modules."""
    forbidden_terms = [
        "platform_gateway",
        "gateway_dispatcher",
        "rbac",
        "ToolPermission",
        "RBACPolicy",
        "X-Correlation-ID",
        "X-User-ID",
        "X-User-Role",
        "X-Production-Write",
        "X-Attachment-Access",
    ]

    pkg_dir = _get_service_package_dir()

    for py_file in pkg_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        relative = py_file.relative_to(pkg_dir)
        for term in forbidden_terms:
            assert term not in content, f"Forbidden term '{term}' found in {relative}"


def test_layer4_public_exports() -> None:
    """Verify platform_investigation_service exports expected public symbols."""
    expected_symbols = [
        "InvestigationApplicationService",
        "InvestigationRequest",
        "InvestigationResult",
        "DiagnosticsSelectionDTO",
        "InvestigationOrchestratorPort",
        "SuperOfficeServicePort",
        "DiagnosticsServicePort",
        "SuperOfficeEvidenceCollector",
        "DiagnosticsEvidenceCollector",
        "KnowledgeEvidenceCollector",
        "DiagnosticLogsEvidenceCollector",
        "LogsEvidenceCollector",
    ]

    for symbol in expected_symbols:
        assert hasattr(platform_investigation_service, symbol), (
            f"Symbol '{symbol}' not exported from platform_investigation_service"
        )


def test_orchestrator_engine_satisfies_layer4_port() -> None:
    """InvestigationOrchestratorEngine structurally satisfies InvestigationOrchestratorPort."""
    engine = InvestigationOrchestratorEngine()
    assert isinstance(engine, InvestigationOrchestratorPort)


def test_layer3_orchestrator_interface_unchanged() -> None:
    """Layer-3 InvestigationOrchestrator Protocol remains unchanged."""
    methods = [m for m in dir(InvestigationOrchestrator) if not m.startswith("_")]
    assert "create_plan" in methods
    assert "advance_step" in methods
    assert "conclude_investigation" in methods


def test_layer3_package_still_has_no_server_imports() -> None:
    """Regression: platform-investigation (Layer 3) still does not import server packages."""
    forbidden_modules = [
        "so_mcp",
        "diag_mcp",
        "kb_mcp",
        "infra_mcp",
        "platform_gateway",
    ]

    investigation_pkg_dir = (
        Path(__file__).parents[3]
        / "src"
        / "shared"
        / "platform-investigation"
        / "src"
        / "platform_investigation"
    )
    assert investigation_pkg_dir.exists()

    for py_file in investigation_pkg_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for forbidden in forbidden_modules:
            assert f"import {forbidden}" not in content, (
                f"Forbidden import '{forbidden}' found in Layer-3 {py_file.name}"
            )
            assert f"from {forbidden}" not in content, (
                f"Forbidden from-import '{forbidden}' found in Layer-3 {py_file.name}"
            )
