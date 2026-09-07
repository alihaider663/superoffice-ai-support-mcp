"""Infrastructure MCP Server process entrypoint."""

import sys

import uvicorn

from infra_mcp.server import create_app
from infra_mcp.settings import InfrastructureServerSettings
from platform_observability.logging import configure_logging, get_logger


def main() -> None:
    """Bootstrap and start the Infrastructure MCP server runtime via Uvicorn."""
    settings = InfrastructureServerSettings()
    configure_logging(settings.logging)
    logger = get_logger("infra_mcp")

    logger.info(
        "infrastructure_mcp_bootstrap_initialized",
        server="infra-mcp",
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
