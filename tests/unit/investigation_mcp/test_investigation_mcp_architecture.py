"""Architecture tests verifying Layer boundaries and dependency invariants for investigation_mcp."""

from pathlib import Path

import pytest

from investigation_mcp.adapters.diagnostics_mcp_adapter import DiagnosticsMcpClientAdapter
from investigation_mcp.adapters.knowledge_mcp_adapter import KnowledgeMcpClientAdapter
from investigation_mcp.adapters.superoffice_mcp_adapter import SuperOfficeMcpClientAdapter
from platform_investigation_service.ports import (
    DiagnosticsServicePort,
    KnowledgeServicePort,
    SuperOfficeServicePort,
)


@pytest.mark.unit
def test_investigation_mcp_does_not_import_gateway():
    """Verify investigation_mcp package contains zero imports from platform_gateway."""
    inv_dir = Path("src/servers/investigation/src/investigation_mcp")
    for py_file in inv_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "platform_gateway" not in content, f"Forbidden Gateway import in {py_file}"


@pytest.mark.unit
def test_investigation_mcp_does_not_import_database_drivers():
    """Verify investigation_mcp package contains zero direct database driver imports."""
    forbidden_drivers = ["aioodbc", "pyodbc", "sqlalchemy", "psycopg2", "asyncpg"]
    inv_dir = Path("src/servers/investigation/src/investigation_mcp")
    for py_file in inv_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for driver in forbidden_drivers:
            assert f"import {driver}" not in content, f"Forbidden DB driver '{driver}' in {py_file}"
            assert f"from {driver}" not in content, f"Forbidden DB driver '{driver}' in {py_file}"


@pytest.mark.unit
def test_investigation_mcp_does_not_import_supabase():
    """Verify investigation_mcp package contains zero Supabase client imports."""
    inv_dir = Path("src/servers/investigation/src/investigation_mcp")
    for py_file in inv_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "supabase" not in content.lower(), f"Forbidden Supabase reference in {py_file}"


@pytest.mark.unit
def test_platform_investigation_service_contains_no_mcp_sdk():
    """Verify Layer-4 platform_investigation_service contains zero imports from mcp SDK."""
    svc_dir = Path("src/services/investigation/src/platform_investigation_service")
    for py_file in svc_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "from mcp" not in content, f"Forbidden MCP SDK import in {py_file}"
        assert "import mcp" not in content, f"Forbidden MCP SDK import in {py_file}"


@pytest.mark.unit
def test_adapters_satisfy_domain_ports():
    """Verify that MCP client adapters satisfy Layer-4 runtime-checkable protocols."""
    assert issubclass(SuperOfficeMcpClientAdapter, SuperOfficeServicePort)
    assert issubclass(DiagnosticsMcpClientAdapter, DiagnosticsServicePort)
    assert issubclass(KnowledgeMcpClientAdapter, KnowledgeServicePort)


@pytest.mark.unit
def test_adapters_expose_no_generic_dispatch_methods():
    """Verify that adapters expose only port methods and no arbitrary tool dispatch method."""
    forbidden_methods = ["call_tool", "execute_tool", "dispatch_tool", "run_tool"]

    adapter_classes = [
        SuperOfficeMcpClientAdapter,
        DiagnosticsMcpClientAdapter,
        KnowledgeMcpClientAdapter,
    ]
    for cls in adapter_classes:
        public_methods = [
            m for m in dir(cls) if not m.startswith("_") and callable(getattr(cls, m))
        ]
        for m in public_methods:
            assert m not in forbidden_methods, (
                f"Generic tool dispatch method '{m}' found in {cls.__name__}"
            )


@pytest.mark.unit
def test_no_infrastructure_mcp_client_in_investigation():
    """Verify no Infrastructure MCP client exists in investigation_mcp."""
    inv_dir = Path("src/servers/investigation/src/investigation_mcp")
    for py_file in inv_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "infra_mcp" not in content, f"Forbidden Infrastructure reference in {py_file}"


@pytest.mark.unit
def test_public_contracts_live_only_in_investigation_mcp():
    """Verify Phase 4.2 public wire contracts are isolated to investigation_mcp."""
    forbidden_dirs = [
        Path("src/shared/platform-investigation"),
        Path("src/services/investigation"),
        Path("src/platform_gateway"),
    ]
    for d in forbidden_dirs:
        for py_file in d.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            assert "InvestigateIncidentRequestDTO" not in content, (
                f"Public DTO leaked into {py_file}"
            )
            assert "InvestigateIncidentResponseDTO" not in content, (
                f"Public DTO leaked into {py_file}"
            )
