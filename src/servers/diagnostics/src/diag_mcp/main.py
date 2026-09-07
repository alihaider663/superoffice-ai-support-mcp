"""Diagnostics MCP Server process entrypoint."""

import sys

import uvicorn

from diag_mcp.server import create_app
from diag_mcp.settings import DiagnosticsServerSettings
from platform_observability.logging import configure_logging, get_logger


def main() -> None:
    """Bootstrap and start the Diagnostics MCP server runtime via Uvicorn."""
    settings = DiagnosticsServerSettings()
    configure_logging(settings.logging)
    logger = get_logger("diag_mcp")

    logger.info(
        "diagnostics_mcp_bootstrap_initialized",
        server="diag-mcp",
        port=settings.port,
        mssql_host=settings.mssql_host,
        transport="Streamable HTTP (ADR 007)",
    )

    app = create_app(settings=settings)
    try:
        uvicorn.run(app, host="127.0.0.1", port=settings.port, log_config=None)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
