"""Pre-Flight Health-Check Engine & Visual Connectivity Dashboard."""

from __future__ import annotations

from platform_core.preflight.cli import print_cli_report
from platform_core.preflight.engine import PreflightEngine, run_preflight_probes
from platform_core.preflight.gui import create_preflight_gui_app, start_gui
from platform_core.preflight.models import (
    PreflightReport,
    ProbeCategory,
    ProbeResult,
    ProbeStatus,
)

__all__ = [
    "PreflightEngine",
    "PreflightReport",
    "ProbeCategory",
    "ProbeResult",
    "ProbeStatus",
    "create_preflight_gui_app",
    "print_cli_report",
    "run_preflight_probes",
    "start_gui",
]
