"""Unit tests for Investigation MCP Server initialization and settings."""

import pytest
from starlette.applications import Starlette

from investigation_mcp.main import app
from investigation_mcp.server import create_app, create_investigation_mcp_server
from investigation_mcp.settings import InvestigationServerSettings


@pytest.mark.unit
def test_investigation_server_settings():
    """Test InvestigationServerSettings defaults and properties."""
    settings = InvestigationServerSettings()
    assert settings.port == 8005
    assert str(settings.superoffice_mcp_url) == "http://127.0.0.1:8001/"
    assert str(settings.diagnostics_mcp_url) == "http://127.0.0.1:8002/"
    assert settings.timeout_seconds == 30


@pytest.mark.unit
def test_create_investigation_mcp_server():
    """Test FastMCP Investigation server creation."""
    server = create_investigation_mcp_server()
    assert server.name == "investigation-mcp-server"
    assert server.settings.stateless_http is True
    assert server.settings.streamable_http_path == "/mcp"


@pytest.mark.unit
def test_create_app():
    """Test Starlette ASGI application initialization."""
    starlette_app = create_app()
    assert isinstance(starlette_app, Starlette)
    assert isinstance(app, Starlette)
