"""Infrastructure MCP Server FastMCP runtime application skeleton (Decision 2A-D07 DEFERRED)."""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from infra_mcp.settings import InfrastructureServerSettings

ALLOWED_BACKEND_HOSTS = [
    "localhost",
    "localhost:*",
    "127.0.0.1",
    "127.0.0.1:*",
    "testserver",
    "testserver:*",
    "infra-backend",
    "infra-backend:*",
    "infra-server",
    "infra-server:*",
    "infra-internal",
    "infra-internal:*",
]


def create_infrastructure_mcp_server() -> FastMCP:
    """Instantiate the structural FastMCP Infrastructure server skeleton.

    Decision 2A-D07 Status: Infrastructure detailed adapter contracts are DEFERRED.
    No unapproved probe capabilities are registered as operational MCP tools.
    """
    return FastMCP(
        name="infrastructure-mcp-server",
        streamable_http_path="/mcp",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=ALLOWED_BACKEND_HOSTS,
        ),
    )


def create_app(
    settings: InfrastructureServerSettings | None = None,  # noqa: ARG001
) -> Starlette:
    """Create the Starlette ASGI application for Infrastructure MCP Server."""
    server = create_infrastructure_mcp_server()
    return server.streamable_http_app()
