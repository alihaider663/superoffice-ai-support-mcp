"""Data models and schemas for the Pre-Flight Health-Check Engine."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ProbeStatus(StrEnum):
    """Execution status for a diagnostic pre-flight probe."""

    SUCCESS = "success"
    WARNING = "warning"
    FAILURE = "failure"
    SKIPPED = "skipped"


class ProbeCategory(StrEnum):
    """Categorization of platform diagnostic probes."""

    APP_SERVERS = "App Servers"
    MSSQL = "MSSQL Database"
    POSTGRES = "PostgreSQL Knowledge"
    CODEBASE = "Codebase Mirror"
    PORTS = "Network Ports"
    SECURITY = "Security & Auth"


class ProbeResult(BaseModel):
    """Structured result of an individual diagnostic probe."""

    name: str = Field(description="Human-readable probe identifier")
    category: ProbeCategory = Field(description="Target subsystem category")
    status: ProbeStatus = Field(description="Probe evaluation outcome")
    latency_ms: float = Field(default=0.0, description="Probe round-trip latency in milliseconds")
    message: str = Field(description="Descriptive outcome summary or error explanation")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Detailed diagnostic metrics and attributes"
    )


class PreflightReport(BaseModel):
    """Comprehensive platform pre-flight evaluation report."""

    timestamp: str = Field(description="ISO-8601 UTC timestamp of report generation")
    overall_status: ProbeStatus = Field(description="Overall platform readiness status")
    ready_to_launch: bool = Field(
        description="True if zero fatal failures detected across all probes"
    )
    passed_count: int = Field(default=0, description="Count of passed probes")
    warning_count: int = Field(default=0, description="Count of warnings")
    failure_count: int = Field(default=0, description="Count of failed probes")
    total_duration_ms: float = Field(
        default=0.0, description="Total diagnostic execution time in ms"
    )
    results: list[ProbeResult] = Field(
        default_factory=list, description="Ordered list of individual probe results"
    )
