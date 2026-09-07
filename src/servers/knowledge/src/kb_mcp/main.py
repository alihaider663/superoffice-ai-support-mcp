"""Knowledge Base MCP Server process entrypoint."""

import sys

import uvicorn

from kb_mcp.server import create_app
from kb_mcp.settings import KnowledgeServerSettings
from platform_observability.logging import configure_logging, get_logger


def main() -> None:
    """Bootstrap and start the Knowledge Base MCP server runtime via Uvicorn."""
    settings = KnowledgeServerSettings()
    configure_logging(settings.logging)
    logger = get_logger("kb_mcp")

    logger.info(
        "knowledge_mcp_bootstrap_initialized",
        server="kb-mcp",
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
