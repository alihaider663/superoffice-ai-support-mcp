"""Unit tests for SuperOfficeServerSettings app_servers configuration."""

from pydantic import HttpUrl

from so_mcp.settings import SuperOfficeServerSettings


def test_app_servers_custom_node_list():
    """Verify that app_servers splits multiple nodes cleanly."""
    settings = SuperOfficeServerSettings(
        api_url=HttpUrl("https://osl-so-iis2.ls.local/SuperOffice"),
        app_servers="https://osl-so-iis2.ls.local/SuperOffice",
    )

    assert settings.app_server_node_urls == ["https://osl-so-iis2.ls.local/SuperOffice"]


def test_app_servers_fallback_to_api_url():
    """Verify that app_server_node_urls falls back to api_url when app_servers is None."""
    settings = SuperOfficeServerSettings(
        api_url=HttpUrl("https://so-active.domain.com/SuperOffice/"),
        app_servers=None,
    )

    assert settings.app_server_node_urls == ["https://so-active.domain.com/SuperOffice"]
