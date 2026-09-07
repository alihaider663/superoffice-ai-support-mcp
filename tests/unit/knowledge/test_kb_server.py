"""Unit tests for Knowledge FastMCP server registration, fail-closed enforcement, and DNS."""

import pytest
from starlette.testclient import TestClient

from kb_mcp.contracts.dtos import (
    KnowledgeSearchResultDomainDTO,
    KnownIssueDomainDTO,
    RunbookDetailDomainDTO,
)
from kb_mcp.contracts.errors import (
    KnowledgeBackendNotConfiguredError,
    KnowledgeSearchError,
    RunbookNotFoundError,
)
from kb_mcp.server import create_app, create_knowledge_mcp_server
from tests.fakes.fake_knowledge_repository import FakeKnowledgeRepository


def test_kb_server_registers_all_3_tools() -> None:
    """Knowledge FastMCP server registers all 3 knowledge and runbook tools."""
    server = create_knowledge_mcp_server()
    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    expected_tools = {
        "search_knowledge",
        "get_runbook",
        "find_known_issues",
    }
    assert tool_names == expected_tools


def test_kb_server_starts_without_backend_and_lists_tools() -> None:
    """Server starts successfully and registers 3 canonical tools with no backend configured."""
    server = create_knowledge_mcp_server(service=None, repository=None)
    assert server is not None
    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    assert tool_names == {"search_knowledge", "get_runbook", "find_known_issues"}


@pytest.mark.asyncio
async def test_search_knowledge_unconfigured_fails_closed() -> None:
    """search_knowledge fails closed when app_service is None."""
    server = create_knowledge_mcp_server(service=None, repository=None)
    tools = server._tool_manager._tools

    with pytest.raises(KnowledgeBackendNotConfiguredError) as exc_info:
        await tools["search_knowledge"].fn(query_text="OAuth")

    assert exc_info.value.error_code == "KNOWLEDGE_BACKEND_NOT_CONFIGURED"
    assert "Knowledge backend is not configured." in str(exc_info.value)
    # Ensure it also conforms to KnowledgeSearchError interface
    assert isinstance(exc_info.value, KnowledgeSearchError)


@pytest.mark.asyncio
async def test_get_runbook_unconfigured_fails_closed() -> None:
    """get_runbook fails closed when app_service is None."""
    server = create_knowledge_mcp_server(service=None, repository=None)
    tools = server._tool_manager._tools

    with pytest.raises(KnowledgeBackendNotConfiguredError) as exc_info:
        await tools["get_runbook"].fn(runbook_id="RB-AUTH-001")

    assert exc_info.value.error_code == "KNOWLEDGE_BACKEND_NOT_CONFIGURED"
    assert "Knowledge backend is not configured." in str(exc_info.value)
    assert isinstance(exc_info.value, KnowledgeSearchError)


@pytest.mark.asyncio
async def test_find_known_issues_unconfigured_fails_closed() -> None:
    """find_known_issues fails closed when app_service is None."""
    server = create_knowledge_mcp_server(service=None, repository=None)
    tools = server._tool_manager._tools

    with pytest.raises(KnowledgeBackendNotConfiguredError) as exc_info:
        await tools["find_known_issues"].fn(query_text="SSO")

    assert exc_info.value.error_code == "KNOWLEDGE_BACKEND_NOT_CONFIGURED"
    assert "Knowledge backend is not configured." in str(exc_info.value)
    assert isinstance(exc_info.value, KnowledgeSearchError)


@pytest.mark.asyncio
async def test_injected_service_still_works() -> None:
    """When a repository/service is injected, all tools function normally."""
    fake_repo = FakeKnowledgeRepository()
    fake_repo.seed_document(
        KnowledgeSearchResultDomainDTO(
            document_id="DOC-AUTH-01",
            title="OAuth Authentication Guide",
            content_excerpt="Details on OAuth 2.0 flow.",
            category="auth",
            relevance_score=0.95,
            source_reference="KB-AUTH-001",
        )
    )
    fake_repo.seed_runbook(
        RunbookDetailDomainDTO(
            runbook_id="RB-AUTH-001",
            title="Authentication Failure Runbook",
            problem_description="Diagnose 401 Unauthorized errors.",
            diagnostic_steps=("Check client secret expiration",),
            remediation_steps=("Regenerate client secret",),
            source_reference="KB-AUTH-001",
        )
    )
    fake_repo.seed_known_issue(
        KnownIssueDomainDTO(
            issue_id="KI-AUTH-01",
            title="ADFS token clock skew",
            symptom_summary="Token validation failure during login.",
            root_cause_summary="Server time drift exceeding 5 minutes.",
            workaround="Sync NTP server clocks.",
            category="auth",
            source_reference="KB-AUTH-001",
        )
    )

    server = create_knowledge_mcp_server(repository=fake_repo)
    tools = server._tool_manager._tools

    # 1. search_knowledge
    search_res = await tools["search_knowledge"].fn(query_text="OAuth")
    assert len(search_res) == 1
    assert search_res[0]["document_id"] == "DOC-AUTH-01"
    assert search_res[0]["title"] == "OAuth Authentication Guide"
    assert search_res[0]["source_reference"] == "KB-AUTH-001"

    # 2. get_runbook
    rb_res = await tools["get_runbook"].fn(runbook_id="RB-AUTH-001")
    assert rb_res["runbook_id"] == "RB-AUTH-001"
    assert rb_res["title"] == "Authentication Failure Runbook"
    assert "Check client secret expiration" in rb_res["diagnostic_steps"]

    # 3. find_known_issues
    issues_res = await tools["find_known_issues"].fn(query_text="ADFS")
    assert len(issues_res) == 1
    assert issues_res[0]["issue_id"] == "KI-AUTH-01"
    assert issues_res[0]["title"] == "ADFS token clock skew"


@pytest.mark.asyncio
async def test_runbook_not_found_remains_distinct_from_unconfigured() -> None:
    """Configured backend with absent runbook raises RunbookNotFoundError (RESOURCE_NOT_FOUND)."""
    fake_repo = FakeKnowledgeRepository()
    server = create_knowledge_mcp_server(repository=fake_repo)
    tools = server._tool_manager._tools

    with pytest.raises(RunbookNotFoundError) as exc_info:
        await tools["get_runbook"].fn(runbook_id="RB-NONEXISTENT")

    assert exc_info.value.error_code == "RESOURCE_NOT_FOUND"
    assert "RB-NONEXISTENT" in str(exc_info.value)
    assert exc_info.value.error_code != "KNOWLEDGE_BACKEND_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_retrieval_failure_remains_distinct_from_unconfigured() -> None:
    """Operational retrieval failure raises KnowledgeSearchError with KNOWLEDGE_SEARCH_ERROR."""
    fake_repo = FakeKnowledgeRepository()
    fake_repo.set_should_fail(True)
    server = create_knowledge_mcp_server(repository=fake_repo)
    tools = server._tool_manager._tools

    with pytest.raises(KnowledgeSearchError) as exc_info:
        await tools["search_knowledge"].fn(query_text="OAuth")

    assert exc_info.value.error_code == "KNOWLEDGE_SEARCH_ERROR"
    assert exc_info.value.error_code != "KNOWLEDGE_BACKEND_NOT_CONFIGURED"


def test_kb_server_mcp_endpoint_invocation_with_configured_service() -> None:
    """Knowledge FastMCP server responds to /mcp tools/call when wired with a repository."""
    fake_repo = FakeKnowledgeRepository()
    fake_repo.seed_document(
        KnowledgeSearchResultDomainDTO(
            document_id="DOC-AUTH-01",
            title="OAuth Authentication Guide",
            content_excerpt="Details on OAuth 2.0 flow.",
            category="auth",
            relevance_score=0.95,
            source_reference="KB-AUTH-001",
        )
    )
    app = create_app(repository=fake_repo)
    with TestClient(app) as client:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "search_knowledge", "arguments": {"query_text": "OAuth"}},
            "id": 1,
        }
        res = client.post(
            "/mcp", json=payload, headers={"Accept": "application/json, text/event-stream"}
        )
        assert res.status_code == 200
        assert "OAuth Authentication Guide" in res.text
        assert "Knowledge Entry" not in res.text


def test_kb_server_mcp_endpoint_unconfigured_fails_closed_no_synthetic() -> None:
    """Unconfigured Knowledge FastMCP server fails closed over /mcp without synthetic data."""
    app = create_app()
    with TestClient(app) as client:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "search_knowledge", "arguments": {"query_text": "OAuth"}},
            "id": 1,
        }
        res = client.post(
            "/mcp", json=payload, headers={"Accept": "application/json, text/event-stream"}
        )
        assert res.status_code == 200
        assert "Knowledge Entry" not in res.text
        # FastMCP returns isError: true when a tool raises an exception
        assert "isError" in res.text or "error" in res.text


def test_kb_server_dns_rebinding_protection() -> None:
    """Allowed host headers pass; unapproved Host headers return 421 Misdirected Request."""
    app = create_app()
    with TestClient(app) as client:
        payload = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        res_ok = client.post(
            "/mcp",
            json=payload,
            headers={"Host": "kb-backend", "Accept": "application/json, text/event-stream"},
        )
        assert res_ok.status_code == 200

        unapproved_headers = {
            "Host": "untrusted-attacker.com",
            "Accept": "application/json, text/event-stream",
        }
        res_denied = client.post("/mcp", json=payload, headers=unapproved_headers)
        assert res_denied.status_code == 421
