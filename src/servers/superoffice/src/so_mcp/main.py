"""SuperOffice CRM MCP Server process entrypoint."""

import sys

import uvicorn

from platform_observability.logging import configure_logging, get_logger
from so_mcp.server import create_app
from so_mcp.settings import SuperOfficeServerSettings


def main() -> None:
    """Bootstrap and start the SuperOffice MCP server runtime via Uvicorn."""
    settings = SuperOfficeServerSettings()
    configure_logging(settings.logging)
    logger = get_logger("so_mcp")

    logger.info(
        "superoffice_mcp_bootstrap_initialized",
        server="so-mcp",
        port=settings.port,
        transport="Streamable HTTP (ADR 007)",
    )

    app = create_app(settings=settings)
    try:
        uvicorn.run(app, host="127.0.0.1", port=settings.port, log_config=None)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
