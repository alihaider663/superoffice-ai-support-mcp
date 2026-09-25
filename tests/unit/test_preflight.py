"""Unit tests for the Pre-Flight Health-Check Engine and Diagnostic Probes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from platform_core.preflight.engine import PreflightEngine
from platform_core.preflight.models import (
    PreflightReport,
    ProbeCategory,
    ProbeResult,
    ProbeStatus,
)
from platform_core.preflight.probes import (
    _tcp_ping,
    probe_codebase_mirror,
    probe_network_ports,
    probe_security_configuration,
    probe_superoffice_cluster,
)


def test_models_serialization() -> None:
    """Verify ProbeResult and PreflightReport models serialize to valid dict/JSON."""
    result = ProbeResult(
        name="Test Probe",
        category=ProbeCategory.APP_SERVERS,
        status=ProbeStatus.SUCCESS,
        latency_ms=12.5,
        message="Node responsive",
        details={"http_status": 200},
    )
    assert result.status == ProbeStatus.SUCCESS
    assert result.latency_ms == 12.5

    report = PreflightReport(
        timestamp="2026-09-25T12:00:00Z",
        overall_status=ProbeStatus.SUCCESS,
        ready_to_launch=True,
        passed_count=1,
        warning_count=0,
        failure_count=0,
        total_duration_ms=15.0,
        results=[result],
    )
    dumped = report.model_dump(mode="json")
    assert dumped["ready_to_launch"] is True
    assert len(dumped["results"]) == 1
    assert dumped["results"][0]["name"] == "Test Probe"


@pytest.mark.asyncio
async def test_tcp_ping_failure_on_closed_port() -> None:
    """Verify _tcp_ping returns False and positive latency for closed port."""
    success, latency, message = await _tcp_ping("127.0.0.1", 59999, timeout=0.2)
    assert success is False
    assert latency >= 0.0
    assert "failed" in message.lower() or "timed out" in message.lower()


@pytest.mark.asyncio
async def test_superoffice_cluster_tenant_isolation_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that including osl-so-iis1 triggers a tenant isolation failure."""
    monkeypatch.setenv("SUPEROFFICE_APP_SERVERS", "https://osl-so-iis1.ls.local/SuperOffice")

    with patch("platform_core.preflight.probes._load_env_file"):
        results = await probe_superoffice_cluster()

    assert len(results) == 1
    assert results[0].status == ProbeStatus.FAILURE
    assert "Tenant Isolation Violation" in results[0].message
    assert results[0].details.get("tenant_violation") is True


@pytest.mark.asyncio
async def test_superoffice_cluster_success_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify successful node probe with mocked TCP and HTTP GET."""
    monkeypatch.setenv("SUPEROFFICE_APP_SERVERS", "https://osl-so-iis2.ls.local/SuperOffice")
    monkeypatch.setenv("SUPEROFFICE_ALLOW_SELF_SIGNED_CERT", "true")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"server": "Microsoft-IIS/10.0"}

    with (
        patch("platform_core.preflight.probes._load_env_file"),
        patch(
            "platform_core.preflight.probes._tcp_ping",
            AsyncMock(return_value=(True, 5.0, "OK")),
        ),
        patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)),
    ):
        results = await probe_superoffice_cluster()

    assert len(results) == 1
    assert results[0].status == ProbeStatus.SUCCESS
    assert "HTTP 200" in results[0].message


@pytest.mark.asyncio
async def test_codebase_mirror_missing_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify warning when codebase mirror directory does not exist."""
    missing_dir = tmp_path / "non_existent_codebase"
    monkeypatch.setenv("SUPEROFFICE_CODEBASE_LOCAL_PATH", str(missing_dir))

    with patch("platform_core.preflight.probes._load_env_file"):
        result = await probe_codebase_mirror()

    assert result.status == ProbeStatus.WARNING
    assert "Directory does not exist" in result.message


@pytest.mark.asyncio
async def test_codebase_mirror_existing_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify success when codebase mirror exists and contains files."""
    mirror_dir = tmp_path / "CodeBase_SuperOffice"
    mirror_dir.mkdir()
    (mirror_dir / "manifest.json").write_text('{"version": 1}', encoding="utf-8")
    scripts_dir = mirror_dir / "ejscript"
    scripts_dir.mkdir()
    (scripts_dir / "test.crmscript").write_text("// test", encoding="utf-8")

    monkeypatch.setenv("SUPEROFFICE_CODEBASE_LOCAL_PATH", str(mirror_dir))

    with patch("platform_core.preflight.probes._load_env_file"):
        result = await probe_codebase_mirror()

    assert result.status == ProbeStatus.SUCCESS
    assert result.details["file_count"] == 2
    assert result.details["has_manifest"] is True


@pytest.mark.asyncio
async def test_probe_network_ports() -> None:
    """Verify network ports probe executes and returns structured result."""
    result = await probe_network_ports()
    assert result.category == ProbeCategory.PORTS
    assert result.status in (ProbeStatus.SUCCESS, ProbeStatus.WARNING)
    assert "available_ports" in result.details


@pytest.mark.asyncio
async def test_probe_security_configuration_warning_on_short_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify security probe flags warning when JWT secret is too short."""
    monkeypatch.setenv("SECURITY_JWT_SECRET_KEY", "short-key")
    monkeypatch.setenv("SECURITY_ENABLE_AUTH", "true")
    monkeypatch.setenv("SECURITY_ENABLE_PII_REDACTION", "true")

    with patch("platform_core.preflight.probes._load_env_file"):
        result = await probe_security_configuration()

    assert result.status == ProbeStatus.WARNING
    assert "too short" in result.message


@pytest.mark.asyncio
async def test_engine_run_aggregates_results() -> None:
    """Verify PreflightEngine aggregates probe results and determines overall readiness."""
    engine = PreflightEngine()

    r1 = ProbeResult(
        name="P1",
        category=ProbeCategory.APP_SERVERS,
        status=ProbeStatus.SUCCESS,
        latency_ms=10.0,
        message="P1 OK",
    )
    r2 = ProbeResult(
        name="P2",
        category=ProbeCategory.MSSQL,
        status=ProbeStatus.WARNING,
        latency_ms=5.0,
        message="P2 Warn",
    )

    with (
        patch(
            "platform_core.preflight.engine.probe_superoffice_cluster",
            AsyncMock(return_value=[r1]),
        ),
        patch("platform_core.preflight.engine.probe_mssql_database", AsyncMock(return_value=r2)),
        patch(
            "platform_core.preflight.engine.probe_postgres_knowledge",
            AsyncMock(return_value=r1),
        ),
        patch("platform_core.preflight.engine.probe_codebase_mirror", AsyncMock(return_value=r1)),
        patch("platform_core.preflight.engine.probe_network_ports", AsyncMock(return_value=r1)),
        patch(
            "platform_core.preflight.engine.probe_security_configuration",
            AsyncMock(return_value=r1),
        ),
    ):
        report = await engine.run()

    assert report.ready_to_launch is True
    assert report.overall_status == ProbeStatus.WARNING
    assert report.passed_count == 5
    assert report.warning_count == 1
    assert report.failure_count == 0
    assert len(report.results) == 6
