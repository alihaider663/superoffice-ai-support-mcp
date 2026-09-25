"""Module entrypoint for executing preflight CLI or GUI via python -m platform_core.preflight."""

from __future__ import annotations

import argparse
import asyncio
import sys

from platform_core.preflight.cli import print_cli_report
from platform_core.preflight.engine import run_preflight_probes
from platform_core.preflight.gui import start_gui


def main() -> int:
    """Parse arguments and dispatch to CLI or GUI runner."""
    parser = argparse.ArgumentParser(
        description="SuperOffice AI Support MCP Platform — Pre-Flight Health-Check Engine"
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the visual interactive browser dashboard instead of terminal CLI",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8088,
        help="Port to bind the visual GUI web server (default: 8088)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address for GUI dashboard (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open default browser when starting GUI",
    )

    args = parser.parse_args()

    if args.gui:
        start_gui(host=args.host, port=args.port, auto_open=not args.no_browser)
        return 0

    report = asyncio.run(run_preflight_probes())
    print_cli_report(report)
    return 0 if report.ready_to_launch else 1


if __name__ == "__main__":
    sys.exit(main())
