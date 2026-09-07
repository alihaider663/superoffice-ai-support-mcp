"""ASGI entrypoint for the Investigation MCP Server."""

from investigation_mcp.server import create_app
from investigation_mcp.settings import InvestigationServerSettings

settings = InvestigationServerSettings()
app = create_app(settings=settings)
