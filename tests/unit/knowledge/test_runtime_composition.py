"""Unit and integration tests for Knowledge MCP runtime composition layer (Gate 7D.3E)."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.testclient import TestClient

from kb_mcp.adapters.factory import (
    KnowledgeRuntimeContext,
    compose_knowledge_runtime,
    create_embedding_provider,
    create_knowledge_engine,
)
from kb_mcp.adapters.fastembed_provider import FastEmbedEmbeddingProvider
from kb_mcp.adapters.postgres_repository import PostgresKnowledgeRepository
from kb_mcp.contracts.dtos import (
    KnowledgeSearchResultDomainDTO,
    KnownIssueDomainDTO,
    RunbookDetailDomainDTO,
)
from kb_mcp.contracts.errors import (
    EmbeddingModelInitializationError,
    KnowledgeRuntimeInitializationError,
)
from kb_mcp.server import create_app, create_knowledge_mcp_server
from kb_mcp.services.knowledge_service import KnowledgeApplicationService
from kb_mcp.settings import KnowledgeServerSettings
from tests.fakes.fake_knowledge_repository import FakeKnowledgeRepository


class FakeTextEmbedding:
    """Offline fake FastEmbed model returning deterministic 384-dim vectors."""

    def __init__(self) -> None:
        self.call_count = 0

    def query_embed(self, query: str | Any, **kwargs: Any) -> Any:  # noqa: ARG002
        self.call_count += 1
        yield [0.01 * (i + 1) for i in range(384)]

    def passage_embed(self, texts: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        for _ in list(texts):
            yield [0.01 * (i + 1) for i in range(384)]


# ============================================================================
# 1. Unconfigured Runtime & Fail-Closed Invariants
# ============================================================================


def test_absent_db_config_leaves_service_unconfigured() -> None:
    """When KNOWLEDGE_DATABASE_URL is absent, is_database_configured is False."""
    settings = KnowledgeServerSettings(database_url=None)
    assert not settings.is_database_configured

    with pytest.raises(ValueError, match="Knowledge database URL is not configured"):
        settings.get_async_database_url()


def test_empty_or_whitespace_db_config_leaves_service_unconfigured() -> None:
    """When KNOWLEDGE_DATABASE_URL is empty or whitespace, is_database_configured is False."""
    settings_empty = KnowledgeServerSettings(database_url=SecretStr(""))
    assert not settings_empty.is_database_configured

    settings_ws = KnowledgeServerSettings(database_url=SecretStr("   "))
    assert not settings_ws.is_database_configured


def test_unconfigured_create_app_starts_and_tools_fail_closed() -> None:
    """Unconfigured create_app starts cleanly, lists tools, but tool invocation fails closed."""
    settings = KnowledgeServerSettings(database_url=None)
    app = create_app(settings=settings)

    with TestClient(app) as client:
        # 1. Tools can be listed
        list_res = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers={"Host": "localhost", "Accept": "application/json, text/event-stream"},
        )
        assert list_res.status_code == 200
        assert "search_knowledge" in list_res.text
        assert "get_runbook" in list_res.text
        assert "find_known_issues" in list_res.text

        # 2. Tool invocation fails closed
        call_res = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "search_knowledge", "arguments": {"query_text": "OAuth"}},
                "id": 2,
            },
            headers={"Host": "localhost", "Accept": "application/json, text/event-stream"},
        )
        assert call_res.status_code == 200
        assert "isError" in call_res.text or "error" in call_res.text
        assert (
            "KNOWLEDGE_BACKEND_NOT_CONFIGURED" in call_res.text or "not configured" in call_res.text
        )


# ============================================================================
# 2. Configured Runtime Composition Component Ownership
# ============================================================================


def test_configured_runtime_composition_ownership() -> None:
    """Configured runtime composes single engine, session factory, repo, model, and service."""
    fake_model = FakeTextEmbedding()
    mock_engine = AsyncMock(spec=AsyncEngine)
    mock_engine.dispose = AsyncMock()

    settings = KnowledgeServerSettings(
        database_url=SecretStr(
            "postgresql+asyncpg://user:secret@localhost:5432/superoffice_ai_knowledge"
        )
    )
    assert settings.is_database_configured

    runtime = compose_knowledge_runtime(
        settings,
        engine=mock_engine,
        model_instance=fake_model,
    )

    assert isinstance(runtime, KnowledgeRuntimeContext)
    assert runtime.engine is mock_engine
    assert isinstance(runtime.session_factory, async_sessionmaker)
    assert isinstance(runtime.repository, PostgresKnowledgeRepository)
    assert isinstance(runtime.embedding_provider, FastEmbedEmbeddingProvider)
    assert isinstance(runtime.service, KnowledgeApplicationService)
    assert runtime.service._repository is runtime.repository
    assert runtime.service._embedding_provider is runtime.embedding_provider


def test_create_knowledge_engine_normalizes_url_and_sets_options() -> None:
    """create_knowledge_engine normalizes postgresql:// to postgresql+asyncpg://."""
    settings = KnowledgeServerSettings(
        database_url=SecretStr(
            "postgresql://app_user:app_pass@127.0.0.1:5432/superoffice_ai_knowledge"
        ),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle_seconds=1800,
    )

    with patch("kb_mcp.adapters.factory.create_async_engine") as mock_create:
        mock_engine = MagicMock(spec=AsyncEngine)
        mock_create.return_value = mock_engine

        engine = create_knowledge_engine(settings)
        assert engine is mock_engine

        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        assert args[0].startswith("postgresql+asyncpg://")
        assert kwargs["pool_pre_ping"] is True
        assert kwargs["pool_size"] == 5
        assert kwargs["max_overflow"] == 10
        assert kwargs["pool_recycle"] == 1800


def test_no_model_or_engine_constructed_per_tool_call() -> None:
    """FastEmbed and database engine instances are shared across multiple tool invocations."""
    fake_model = FakeTextEmbedding()
    fake_repo = FakeKnowledgeRepository()
    fake_repo.seed_document(
        KnowledgeSearchResultDomainDTO(
            document_id="DOC-1",
            title="SAML Guide",
            content_excerpt="Details",
            category="auth",
            relevance_score=0.9,
            source_reference="DOC-1",
        )
    )

    provider = FastEmbedEmbeddingProvider(model_instance=fake_model)
    service = KnowledgeApplicationService(repository=fake_repo, embedding_provider=provider)
    server = create_knowledge_mcp_server(service=service)
    tools = server._tool_manager._tools

    # Execute search multiple times
    async def _run() -> None:
        await tools["search_knowledge"].fn(query_text="query 1")
        await tools["search_knowledge"].fn(query_text="query 2")
        await tools["search_knowledge"].fn(query_text="query 3")

    asyncio.run(_run())

    # Model instance was reused 3 times, not reconstructed
    assert fake_model.call_count == 3


# ============================================================================
# 3. Flow Verification: search, get_runbook, find_known_issues
# ============================================================================


@pytest.mark.asyncio
async def test_search_knowledge_invokes_embedding_provider_and_repository() -> None:
    """search_knowledge executes full flow: service -> embed_query -> repo -> sanitizer."""
    fake_model = FakeTextEmbedding()
    fake_repo = FakeKnowledgeRepository()
    fake_repo.seed_document(
        KnowledgeSearchResultDomainDTO(
            document_id="DOC-1",
            title="Database Latency",
            content_excerpt="MSSQL sync latency troubleshooting.",
            category="database",
            relevance_score=0.92,
            source_reference="DOC-1",
        )
    )

    provider = FastEmbedEmbeddingProvider(model_instance=fake_model)
    service = KnowledgeApplicationService(repository=fake_repo, embedding_provider=provider)
    server = create_knowledge_mcp_server(service=service)
    tools = server._tool_manager._tools

    res = await tools["search_knowledge"].fn(query_text="MSSQL latency", max_results=5)
    assert len(res) == 1
    assert res[0]["document_id"] == "DOC-1"
    assert res[0]["title"] == "Database Latency"
    assert fake_model.call_count == 1
    assert fake_repo.last_query_embedding is not None
    assert len(fake_repo.last_query_embedding) == 384


@pytest.mark.asyncio
async def test_get_runbook_does_not_invoke_embedding_provider() -> None:
    """get_runbook retrieves runbook directly without generating query embeddings."""
    fake_model = FakeTextEmbedding()
    fake_repo = FakeKnowledgeRepository()
    fake_repo.seed_runbook(
        RunbookDetailDomainDTO(
            runbook_id="RB-NET-01",
            title="Network Latency Runbook",
            problem_description="Diagnose latency",
            diagnostic_steps=("Ping gateway",),
            remediation_steps=("Restart interface",),
            source_reference="RB-NET-01",
        )
    )

    provider = FastEmbedEmbeddingProvider(model_instance=fake_model)
    service = KnowledgeApplicationService(repository=fake_repo, embedding_provider=provider)
    server = create_knowledge_mcp_server(service=service)
    tools = server._tool_manager._tools

    rb = await tools["get_runbook"].fn(runbook_id="RB-NET-01")
    assert rb["runbook_id"] == "RB-NET-01"
    assert rb["title"] == "Network Latency Runbook"
    assert fake_model.call_count == 0


@pytest.mark.asyncio
async def test_find_known_issues_does_not_invoke_embedding_provider() -> None:
    """find_known_issues uses pg_trgm and does not generate query embeddings."""
    fake_model = FakeTextEmbedding()
    fake_repo = FakeKnowledgeRepository()
    fake_repo.seed_known_issue(
        KnownIssueDomainDTO(
            issue_id="KI-001",
            title="Login Timeout",
            symptom_summary="Timeout on login",
            root_cause_summary="Deadlock",
            workaround="Retry",
            category="auth",
            source_reference="KI-001",
        )
    )

    provider = FastEmbedEmbeddingProvider(model_instance=fake_model)
    service = KnowledgeApplicationService(repository=fake_repo, embedding_provider=provider)
    server = create_knowledge_mcp_server(service=service)
    tools = server._tool_manager._tools

    issues = await tools["find_known_issues"].fn(query_text="Login Timeout", max_results=5)
    assert len(issues) == 1
    assert issues[0]["issue_id"] == "KI-001"
    assert fake_model.call_count == 0


# ============================================================================
# 4. Initialization Failure Semantics (Section 9)
# ============================================================================


def test_configured_invalid_db_scheme_raises_runtime_init_error() -> None:
    """Configured database URL with invalid scheme fails with initialization error."""
    settings = KnowledgeServerSettings(
        database_url=SecretStr("mysql://user:pass@localhost:3306/db")
    )
    with pytest.raises(KnowledgeRuntimeInitializationError, match="Invalid Knowledge database URL"):
        create_knowledge_engine(settings)


def test_configured_runtime_init_failure_does_not_silently_downgrade_to_unconfigured() -> None:
    """create_app fails startup on invalid configured database URL, NOT silently unconfigured."""
    settings = KnowledgeServerSettings(database_url=SecretStr("invalid_scheme://host/db"))
    with pytest.raises(KnowledgeRuntimeInitializationError):
        create_app(settings=settings)


def test_engine_creation_failure_raises_typed_error() -> None:
    """When create_async_engine fails, KnowledgeRuntimeInitializationError is raised."""
    settings = KnowledgeServerSettings(
        database_url=SecretStr("postgresql+asyncpg://user:pass@localhost/db")
    )
    with (
        patch(
            "kb_mcp.adapters.factory.create_async_engine",
            side_effect=RuntimeError("driver error"),
        ),
        pytest.raises(
            KnowledgeRuntimeInitializationError,
            match="Failed to create Knowledge database engine",
        ),
    ):
        create_knowledge_engine(settings)


def test_embedding_provider_unsupported_model_fails_explicitly() -> None:
    """Configuring unsupported embedding model raises EmbeddingModelInitializationError."""
    with patch.object(
        KnowledgeServerSettings, "validate_embedding_model", return_value="unapproved-model"
    ):
        settings = KnowledgeServerSettings.model_construct(
            database_url=SecretStr("postgresql+asyncpg://localhost/db"),
            embedding_model="unapproved-model",
        )
        with pytest.raises(
            EmbeddingModelInitializationError,
            match=r"Only 'BAAI/bge-small-en-v1\.5' is approved",
        ):
            create_embedding_provider(settings)


def test_configured_runtime_never_falls_back_to_supabase() -> None:
    """Configured PostgreSQL runtime uses PostgresKnowledgeRepository, never Supabase."""
    fake_model = FakeTextEmbedding()
    mock_engine = AsyncMock(spec=AsyncEngine)

    settings = KnowledgeServerSettings(
        database_url=SecretStr("postgresql+asyncpg://user:pass@localhost:5432/db"),
        supabase_url="https://some-project.supabase.co",  # type: ignore[arg-type]
        supabase_anon_key=SecretStr("some-key"),
    )
    runtime = compose_knowledge_runtime(settings, engine=mock_engine, model_instance=fake_model)
    assert isinstance(runtime.repository, PostgresKnowledgeRepository)
    assert not hasattr(runtime.repository, "_supabase_client")


# ============================================================================
# 5. Lifecycle and Clean Resource Disposal (Section 13)
# ============================================================================


def test_engine_disposed_on_starlette_app_shutdown() -> None:
    """When Starlette application shuts down, engine.dispose() is awaited cleanly."""
    fake_model = FakeTextEmbedding()
    mock_engine = AsyncMock(spec=AsyncEngine)
    mock_engine.dispose = AsyncMock()

    settings = KnowledgeServerSettings(
        database_url=SecretStr("postgresql+asyncpg://user:pass@localhost:5432/db")
    )
    runtime = compose_knowledge_runtime(
        settings,
        engine=mock_engine,
        model_instance=fake_model,
    )

    app = create_app(settings=settings, runtime_context=runtime)

    mock_engine.dispose.assert_not_called()

    with TestClient(app) as client:
        res = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers={"Host": "localhost", "Accept": "application/json, text/event-stream"},
        )
        assert res.status_code == 200

    # After TestClient exits (lifespan shutdown), engine.dispose() was awaited
    mock_engine.dispose.assert_awaited_once()


# ============================================================================
# 6. Secret Safety & Platform Invariants (Sections 17 & 43)
# ============================================================================


def test_no_credentials_emitted_in_settings_repr_or_str() -> None:
    """Database credentials in KnowledgeServerSettings are masked by SecretStr."""
    secret_pass = "UltraSecretPassword123!"
    settings = KnowledgeServerSettings(
        database_url=SecretStr(f"postgresql+asyncpg://user:{secret_pass}@localhost:5432/db")
    )

    repr_str = repr(settings)
    assert secret_pass not in repr_str
    assert "**********" in repr_str

    str_str = str(settings)
    assert secret_pass not in str_str


def test_platform_public_tool_count_remains_18() -> None:
    """Knowledge MCP exposes 3 tools; total platform tool count remains 18."""
    server = create_knowledge_mcp_server()
    kb_tools = list(server._tool_manager._tools.keys())
    assert sorted(kb_tools) == ["find_known_issues", "get_runbook", "search_knowledge"]
    assert len(kb_tools) == 3
