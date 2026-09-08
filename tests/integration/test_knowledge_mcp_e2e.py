"""Official MCP SDK End-to-End Verification Suite for Knowledge MCP Gate 7D.4."""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from kb_mcp.contracts.dtos import (
    KnowledgeSearchResultDomainDTO,
    KnownIssueDomainDTO,
    RunbookDetailDomainDTO,
)
from kb_mcp.server import create_app
from kb_mcp.settings import KnowledgeServerSettings
from tests.fakes.fake_knowledge_repository import FakeKnowledgeRepository


def _get_configured_database_url() -> str | None:
    env_url = os.getenv("KNOWLEDGE_DATABASE_URL")
    if env_url and env_url.strip():
        return env_url.strip()
    settings = KnowledgeServerSettings()
    if settings.is_database_configured and settings.database_url:
        return settings.database_url.get_secret_value().strip()
    return None


LOCAL_PG_URL = _get_configured_database_url()


def _get_text(res: CallToolResult, index: int = 0) -> str:
    """Extract text from TextContent block safely for mypy."""
    assert len(res.content) > index
    block = res.content[index]
    assert isinstance(block, TextContent)
    return block.text


def _get_texts(res: CallToolResult) -> list[str]:
    """Extract all text contents safely for mypy."""
    texts: list[str] = []
    for block in res.content:
        assert isinstance(block, TextContent)
        texts.append(block.text)
    return texts


@asynccontextmanager
async def official_kb_session(app: Any) -> AsyncIterator[ClientSession]:
    """Open an official MCP ClientSession over Streamable HTTP to Knowledge MCP."""
    transport = httpx.ASGITransport(app=app)
    headers = {"Host": "localhost", "Accept": "application/json, text/event-stream"}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=transport, base_url="http://localhost", headers=headers
        ) as http_client,
        streamable_http_client("http://localhost/mcp", http_client=http_client) as (r, w, _),
        ClientSession(r, w) as session,
    ):
        await session.initialize()
        yield session


def _create_seeded_fake_repo() -> FakeKnowledgeRepository:
    repo = FakeKnowledgeRepository()
    repo.seed_document(
        KnowledgeSearchResultDomainDTO(
            document_id="sample-doc-postgres-timeout",
            title="PostgreSQL Connection Timeout Troubleshooting",
            content_excerpt="Applications encounter PostgreSQL connection timeouts...",
            category="troubleshooting",
            relevance_score=0.8694,
            source_reference="sample://knowledge/postgresql-connection-timeout",
        )
    )
    repo.seed_runbook(
        RunbookDetailDomainDTO(
            runbook_id="sample-rb-postgres-timeout",
            title="Resolve PostgreSQL Connection Timeouts",
            problem_description="Diagnose and resolve connection checkout timeouts.",
            diagnostic_steps=("Check database liveness", "Inspect active connections"),
            remediation_steps=("Terminate idle sessions", "Increase max_connections"),
            source_reference="sample://knowledge/postgresql-connection-timeout",
        )
    )
    repo.seed_known_issue(
        KnownIssueDomainDTO(
            issue_id="sample-ki-db-pool-exhaustion",
            title="Database Connection Pool Exhaustion Causes Request Timeouts",
            symptom_summary="Services report connection timeout after 5 seconds.",
            root_cause_summary="Connection pool size insufficient for peak concurrency.",
            workaround="Increase pool size and verify connection checkout timeout.",
            category="database",
            source_reference="sample://knowledge/db-pool-exhaustion",
        )
    )
    return repo


async def _is_live_postgres_accessible() -> bool:
    if not LOCAL_PG_URL:
        return False
    try:
        engine = create_async_engine(LOCAL_PG_URL)
        async with engine.connect() as conn:
            val = (
                await conn.execute(text("SELECT count(1) FROM knowledge.documents"))
            ).scalar_one()
            await engine.dispose()
            return bool(val == 3)
    except Exception:
        return False


@pytest.mark.asyncio
async def test_official_mcp_initialization_and_tool_discovery() -> None:
    """Official MCP client connects over Streamable HTTP and discovers exactly 3 tools."""
    fake_repo = _create_seeded_fake_repo()
    app = create_app(repository=fake_repo)

    async with official_kb_session(app) as session:
        tools_res = await session.list_tools()
        tools = {t.name: t for t in tools_res.tools}

        assert set(tools.keys()) == {"search_knowledge", "get_runbook", "find_known_issues"}
        assert len(tools) == 3

        sk_props = set(tools["search_knowledge"].inputSchema.get("properties", {}).keys())
        assert "query_text" in sk_props
        assert "max_results" in sk_props
        assert not sk_props.intersection({"embedding", "query_vector", "dimension", "model", "sql"})

        rb_props = set(tools["get_runbook"].inputSchema.get("properties", {}).keys())
        assert rb_props == {"runbook_id"}

        ki_props = set(tools["find_known_issues"].inputSchema.get("properties", {}).keys())
        assert "query_text" in ki_props
        assert "max_results" in ki_props
        assert not ki_props.intersection({"product", "version", "embedding", "table", "sql"})


@pytest.mark.asyncio
async def test_official_mcp_unconfigured_mode_fails_closed() -> None:
    """When unconfigured, all tools fail closed with KNOWLEDGE_BACKEND_NOT_CONFIGURED."""
    settings = KnowledgeServerSettings(database_url=None)
    app = create_app(settings=settings)

    async with official_kb_session(app) as session:
        tools_res = await session.list_tools()
        assert len(tools_res.tools) == 3

        call_sk = await session.call_tool("search_knowledge", arguments={"query_text": "test"})
        assert call_sk.isError is True
        assert "Knowledge backend is not configured" in _get_text(call_sk)

        call_rb = await session.call_tool("get_runbook", arguments={"runbook_id": "sample-rb-01"})
        assert call_rb.isError is True
        assert "Knowledge backend is not configured" in _get_text(call_rb)

        call_ki = await session.call_tool("find_known_issues", arguments={"query_text": "test"})
        assert call_ki.isError is True
        assert "Knowledge backend is not configured" in _get_text(call_ki)


@pytest.mark.asyncio
async def test_official_mcp_configured_calls_and_result_minimization() -> None:
    """Configured tools return minimized fields without internal or database leakage."""
    fake_repo = _create_seeded_fake_repo()
    app = create_app(repository=fake_repo)

    async with official_kb_session(app) as session:
        sk_res = await session.call_tool("search_knowledge", arguments={"query_text": "PostgreSQL"})
        assert sk_res.isError is False
        first_doc = json.loads(_get_text(sk_res))
        expected_sk_keys = {
            "document_id",
            "title",
            "content_excerpt",
            "category",
            "relevance_score",
            "source_reference",
        }
        assert set(first_doc.keys()) == expected_sk_keys
        assert not set(first_doc.keys()).intersection(
            {"embedding", "canonical_content", "content_hash", "table_name", "file_path"}
        )
        assert 0.0 <= first_doc["relevance_score"] <= 1.0

        invalid_res = await session.call_tool("search_knowledge", arguments={"query_text": "   "})
        assert invalid_res.isError is True
        assert "validation error" in _get_text(invalid_res).lower()
        assert "sql" not in _get_text(invalid_res).lower()

        rb_res = await session.call_tool(
            "get_runbook", arguments={"runbook_id": "sample-rb-postgres-timeout"}
        )
        assert rb_res.isError is False
        rb = json.loads(_get_text(rb_res))
        expected_rb_keys = {
            "runbook_id",
            "title",
            "problem_description",
            "diagnostic_steps",
            "remediation_steps",
            "source_reference",
        }
        assert set(rb.keys()) == expected_rb_keys
        assert len(rb["diagnostic_steps"]) > 0
        assert len(rb["remediation_steps"]) > 0

        rb_nf = await session.call_tool(
            "get_runbook", arguments={"runbook_id": "sample-rb-does-not-exist"}
        )
        assert rb_nf.isError is True
        assert "not found" in _get_text(rb_nf).lower()
        assert "select" not in _get_text(rb_nf).lower()

        ki_res = await session.call_tool(
            "find_known_issues", arguments={"query_text": "Connection Pool"}
        )
        assert ki_res.isError is False
        first_ki = json.loads(_get_text(ki_res))
        expected_ki_keys = {
            "issue_id",
            "title",
            "symptom_summary",
            "workaround",
            "source_reference",
        }
        assert set(first_ki.keys()) == expected_ki_keys


@pytest.mark.asyncio
async def test_official_mcp_live_postgres_and_fastembed_e2e() -> None:  # noqa: PLR0915
    """Full E2E against live PostgreSQL superoffice_ai_knowledge and local FastEmbed."""
    if not LOCAL_PG_URL or not await _is_live_postgres_accessible():
        pytest.skip("Live PostgreSQL superoffice_ai_knowledge database is not accessible.")

    engine = create_async_engine(LOCAL_PG_URL)
    async with engine.connect() as conn:
        before_docs = (
            await conn.execute(text("SELECT count(1) FROM knowledge.documents"))
        ).scalar_one()
        before_chunks = (
            await conn.execute(text("SELECT count(1) FROM knowledge.chunks"))
        ).scalar_one()
        before_rbs = (
            await conn.execute(text("SELECT count(1) FROM knowledge.runbooks"))
        ).scalar_one()
        before_kis = (
            await conn.execute(text("SELECT count(1) FROM knowledge.known_issues"))
        ).scalar_one()
    await engine.dispose()

    assert (before_docs, before_chunks, before_rbs, before_kis) == (3, 6, 3, 3)

    settings = KnowledgeServerSettings(database_url=SecretStr(LOCAL_PG_URL))
    app = create_app(settings=settings)

    async with official_kb_session(app) as session:
        res_pg = await session.call_tool(
            "search_knowledge",
            arguments={"query_text": "PostgreSQL connection timeout", "max_results": 3},
        )
        assert res_pg.isError is False
        top_pg = json.loads(_get_text(res_pg))
        assert top_pg["document_id"] == "sample-doc-postgres-timeout"
        assert top_pg["title"] == "PostgreSQL Connection Timeout Troubleshooting"
        assert top_pg["source_reference"] == "sample://knowledge/postgresql-connection-timeout"
        assert 0.0 <= top_pg["relevance_score"] <= 1.0

        res_jwt = await session.call_tool(
            "search_knowledge",
            arguments={"query_text": "API returns 401 after token expiration", "max_results": 3},
        )
        assert res_jwt.isError is False
        top_jwt = json.loads(_get_text(res_jwt))
        assert top_jwt["document_id"] == "sample-doc-api-auth-failure"
        assert top_jwt["title"] == "API JWT Authentication Failure Troubleshooting"
        assert top_jwt["source_reference"] == "sample://knowledge/api-authentication-failure"

        res_iis = await session.call_tool(
            "search_knowledge",
            arguments={"query_text": "IIS application pool stopped", "max_results": 3},
        )
        assert res_iis.isError is False
        top_iis = json.loads(_get_text(res_iis))
        assert top_iis["document_id"] == "sample-doc-iis-app-pool"
        assert top_iis["title"] == "IIS Application Pool Unavailable Troubleshooting"
        assert top_iis["source_reference"] == "sample://knowledge/iis-application-pool-unavailable"

        rb1_res = await session.call_tool(
            "get_runbook", arguments={"runbook_id": "sample-rb-postgres-timeout"}
        )
        assert rb1_res.isError is False
        assert json.loads(_get_text(rb1_res))["title"] == "Resolve PostgreSQL Connection Timeouts"

        rb2_res = await session.call_tool(
            "get_runbook", arguments={"runbook_id": "sample-rb-api-auth-failure"}
        )
        assert rb2_res.isError is False
        assert json.loads(_get_text(rb2_res))["title"] == "Resolve API JWT Authentication Failures"

        rb3_res = await session.call_tool(
            "get_runbook", arguments={"runbook_id": "sample-rb-iis-app-pool"}
        )
        assert rb3_res.isError is False
        assert (
            json.loads(_get_text(rb3_res))["title"] == "Recover an Unavailable IIS Application Pool"
        )

        rb_nf_res = await session.call_tool(
            "get_runbook", arguments={"runbook_id": "sample-rb-does-not-exist"}
        )
        assert rb_nf_res.isError is True
        assert "not found" in _get_text(rb_nf_res).lower()

        ki1_res = await session.call_tool(
            "find_known_issues",
            arguments={"query_text": "Database Connection Pool Exhaustion", "max_results": 3},
        )
        assert ki1_res.isError is False
        ki1 = json.loads(_get_text(ki1_res))
        assert ki1["issue_id"] == "sample-ki-db-pool-exhaustion"
        assert "Connection Pool Exhaustion" in ki1["title"]

        ki2_res = await session.call_tool(
            "find_known_issues",
            arguments={"query_text": "JWT Token Expiration", "max_results": 3},
        )
        assert ki2_res.isError is False
        ki2 = json.loads(_get_text(ki2_res))
        assert ki2["issue_id"] == "sample-ki-jwt-expiration"
        assert "JWT Token Expiration" in ki2["title"]

        ki3_res = await session.call_tool(
            "find_known_issues",
            arguments={"query_text": "IIS Worker Process Recycle Loop", "max_results": 3},
        )
        assert ki3_res.isError is False
        ki3 = json.loads(_get_text(ki3_res))
        assert ki3["issue_id"] == "sample-ki-iis-recycle-loop"
        assert "Recycle Loop" in ki3["title"]

    engine2 = create_async_engine(LOCAL_PG_URL)
    async with engine2.connect() as conn:
        after_docs = (
            await conn.execute(text("SELECT count(1) FROM knowledge.documents"))
        ).scalar_one()
        after_chunks = (
            await conn.execute(text("SELECT count(1) FROM knowledge.chunks"))
        ).scalar_one()
        after_rbs = (
            await conn.execute(text("SELECT count(1) FROM knowledge.runbooks"))
        ).scalar_one()
        after_kis = (
            await conn.execute(text("SELECT count(1) FROM knowledge.known_issues"))
        ).scalar_one()
    await engine2.dispose()

    assert (after_docs, after_chunks, after_rbs, after_kis) == (3, 6, 3, 3)
