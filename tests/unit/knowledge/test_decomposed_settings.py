"""Unit tests for KnowledgeServerSettings decomposed connection parameters."""

import pytest
from pydantic import SecretStr

from kb_mcp.settings import KnowledgeServerSettings


def test_decomposed_parameters_builds_asyncpg_url():
    """Verify that discrete parameters build a valid postgresql+asyncpg URL."""
    settings = KnowledgeServerSettings(
        database_host="127.0.0.1",
        database_port=5432,
        database_name="superoffice_ai_knowledge",
        database_user="postgres",
        database_password=SecretStr("Master@102"),
        database_url=None,
    )

    assert settings.is_database_configured is True
    built_url = settings.get_async_database_url()
    # Verify that @ in password is automatically URL-encoded to %40
    assert (
        built_url
        == "postgresql+asyncpg://postgres:Master%40102@127.0.0.1:5432/superoffice_ai_knowledge"
    )


def test_decomposed_parameters_without_password():
    """Verify discrete parameters build valid URL when password is empty or None."""
    settings = KnowledgeServerSettings(
        database_host="localhost",
        database_port=5432,
        database_name="testdb",
        database_user="appuser",
        database_password=None,
        database_url=None,
    )

    assert settings.is_database_configured is True
    assert settings.get_async_database_url() == "postgresql+asyncpg://appuser@localhost:5432/testdb"


def test_legacy_composite_url_fallback():
    """Verify that composite database_url is used when discrete parameters are absent."""
    settings = KnowledgeServerSettings(
        database_host=None,
        database_name=None,
        database_user=None,
        database_url=SecretStr("postgresql://usr:pass@remote:5433/knowledgedb"),
    )

    assert settings.is_database_configured is True
    assert (
        settings.get_async_database_url() == "postgresql+asyncpg://usr:pass@remote:5433/knowledgedb"
    )


def test_unconfigured_settings_raises_value_error():
    """Verify that unconfigured settings raise a clear ValueError."""
    settings = KnowledgeServerSettings(
        database_host=None,
        database_name=None,
        database_user=None,
        database_url=None,
    )

    assert settings.is_database_configured is False
    with pytest.raises(ValueError, match="Knowledge database URL is not configured"):
        settings.get_async_database_url()
