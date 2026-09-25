"""Command-line interface (CLI) runner for Pre-Flight Health-Check Engine."""

from __future__ import annotations

import asyncio
import sys

from platform_core.preflight.engine import run_preflight_probes
from platform_core.preflight.models import PreflightReport, ProbeStatus

# ANSI escape color constants
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
GRAY = "\033[90m"


def format_status_badge(status: ProbeStatus) -> str:
    """Return a color-coded status badge."""
    match status:
        case ProbeStatus.SUCCESS:
            return f"{GREEN}[PASS]{RESET}"
        case ProbeStatus.WARNING:
            return f"{YELLOW}[WARN]{RESET}"
        case ProbeStatus.FAILURE:
            return f"{RED}[FAIL]{RESET}"
        case ProbeStatus.SKIPPED:
            return f"{GRAY}[SKIP]{RESET}"


def print_cli_report(report: PreflightReport) -> None:
    """Render structured terminal report to stdout."""
    print()
    print(
        f"{CYAN}{BOLD}========================================================================{RESET}"
    )
    print(f"{CYAN}{BOLD} SuperOffice AI Support MCP Platform - Pre-Flight Diagnostic Probes{RESET}")
    print(
        f"{CYAN}{BOLD}========================================================================{RESET}"
    )
    print(f"{GRAY}Generated: {report.timestamp} | Duration: {report.total_duration_ms}ms{RESET}")
    print()

    current_cat = None
    for res in report.results:
        if res.category != current_cat:
            current_cat = res.category
            cat_label = current_cat.value if hasattr(current_cat, "value") else str(current_cat)
            print(f"{BOLD}[{cat_label}]{RESET}")

        badge = format_status_badge(res.status)
        lat = f"{res.latency_ms:.1f}ms" if res.latency_ms > 0 else "-"
        print(f"  {badge} {BOLD}{res.name}{RESET} {GRAY}({lat}){RESET}")
        print(f"       {res.message}")

    print()
    print(f"{CYAN}------------------------------------------------------------------------{RESET}")
    print(
        f"Summary: {GREEN}{report.passed_count} Passed{RESET} | "
        f"{YELLOW}{report.warning_count} Warnings{RESET} | "
        f"{RED}{report.failure_count} Failed{RESET}"
    )

    if report.ready_to_launch:
        print(
            f"{GREEN}{BOLD}[READY] All critical probes passed. Platform is safe to launch!{RESET}"
        )
    else:
        print(
            f"{RED}{BOLD}[NOT READY] Critical failures detected. "
            f"Resolve blocking issues before startup.{RESET}"
        )
    print(f"{CYAN}========================================================================{RESET}")
    print()


def main() -> int:
    """Synchronous entrypoint for CLI execution."""
    report = asyncio.run(run_preflight_probes())
    print_cli_report(report)
    return 0 if report.ready_to_launch else 1


if __name__ == "__main__":
    sys.exit(main())
