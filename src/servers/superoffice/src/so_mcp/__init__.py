"""SuperOffice Core CRM MCP Server package."""

from so_mcp.adapters.factory import create_superoffice_client
from so_mcp.adapters.rest_client import SuperOfficeRestClient
from so_mcp.services.ticket_service import SuperOfficeApplicationService
from so_mcp.settings import SuperOfficeServerSettings

__all__ = [
    "SuperOfficeApplicationService",
    "SuperOfficeRestClient",
    "SuperOfficeServerSettings",
    "create_superoffice_client",
]
