"""Unit tests for SupabaseKnowledgeRepository mapping, bounding, and error redaction."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import HttpUrl, SecretStr

from kb_mcp.adapters.supabase_repository import SupabaseKnowledgeRepository
from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnownIssueSearchCriteriaDTO,
)
from kb_mcp.contracts.errors import (
    KnowledgeSearchError,
    RunbookNotFoundError,
)
from kb_mcp.settings import KnowledgeServerSettings


@pytest.fixture
def mock_settings() -> KnowledgeServerSettings:
    """Create test settings for Knowledge server with test mappings."""
    return KnowledgeServerSettings(
        supabase_url=HttpUrl("https://testproject.supabase.co"),
        supabase_anon_key=SecretStr("test-anon-key-1234567890"),
        match_documents_rpc="match_documents",
        runbooks_table="runbooks",
        known_issues_table="known_issues",
        timeout_seconds=5,
        max_search_results=5,
    )


@pytest.fixture
def unconfigured_settings() -> KnowledgeServerSettings:
    """Create test settings with default unconfigured backend mappings (None)."""
    return KnowledgeServerSettings(
        supabase_url=HttpUrl("https://testproject.supabase.co"),
        supabase_anon_key=SecretStr("test-anon-key-1234567890"),
        match_documents_rpc=None,
        runbooks_table=None,
        known_issues_table=None,
        timeout_seconds=5,
        max_search_results=5,
    )


def _create_mock_response(status_code: int = 200, json_data: Any = None) -> MagicMock:
    """Create a mock httpx.Response."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status_code
    mock_resp.json = MagicMock(return_value=json_data)
    if 200 <= status_code < 300:
        mock_resp.raise_for_status = MagicMock()
    else:
        req = MagicMock(spec=httpx.Request)
        req.url = "https://testproject.supabase.co/rest/v1/rpc/match_documents"
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                message=f"HTTP {status_code} Error",
                request=req,
                response=mock_resp,
            )
        )
    return mock_resp


@pytest.mark.asyncio
async def test_search_knowledge_success(mock_settings: KnowledgeServerSettings) -> None:
    """search_knowledge correctly maps PostgREST RPC JSON response to Domain DTOs."""
    raw_payload = [
        {
            "document_id": "DOC-101",
            "title": "SuperOffice SSO Configuration",
            "content_excerpt": "Configure SAML 2.0 Identity Provider integration.",
            "category": "authentication",
            "product": "SuperOffice CRM",
            "version": "10.2",
            "tags": ["sso", "saml", "idp"],
            "similarity": 0.95,
            "source_reference": "KB-AUTH-101",
        },
        {
            "id": "DOC-102",
            "title": "Legacy ADFS Setup",
            "content": "Configure ADFS relying party trust.",
            "category": "authentication",
            "score": "invalid_score",
            "tags": "adfs, legacy, auth",
            "source_reference": "KB-AUTH-102",
        },
    ]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=_create_mock_response(200, raw_payload))

    repo = SupabaseKnowledgeRepository(settings=mock_settings, http_client=mock_client)
    criteria = KnowledgeSearchCriteriaDTO(
        query_text="SAML SSO",
        category="authentication",
        product="SuperOffice CRM",
        version="10.2",
        limit=5,
    )

    results = await repo.search_knowledge(criteria)
    assert len(results) == 2

    # Verify field mappings
    assert results[0].document_id == "DOC-101"
    assert results[0].title == "SuperOffice SSO Configuration"
    assert results[0].relevance_score == 0.95
    assert results[0].tags == ("sso", "saml", "idp")
    assert results[0].source_reference == "KB-AUTH-101"

    assert results[1].document_id == "DOC-102"
    assert results[1].relevance_score == 0.0
    assert results[1].tags == ("adfs", "legacy", "auth")


@pytest.mark.asyncio
async def test_search_knowledge_threshold_and_limit(
    mock_settings: KnowledgeServerSettings,
) -> None:
    """search_knowledge respects min_relevance_score filter and limit bounds."""
    raw_payload = [
        {"document_id": f"DOC-{i}", "title": f"Doc {i}", "similarity": 0.90 - (i * 0.1)}
        for i in range(10)
    ]
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=_create_mock_response(200, raw_payload))

    repo = SupabaseKnowledgeRepository(settings=mock_settings, http_client=mock_client)

    # 1. Filter by min_relevance_score = 0.85 (should keep 0.90 and 0.80 -> only 0.90)
    results = await repo.search_knowledge(
        KnowledgeSearchCriteriaDTO(query_text="test", min_relevance_score=0.85, limit=5)
    )
    assert len(results) == 1
    assert results[0].relevance_score == 0.90


@pytest.mark.asyncio
async def test_search_knowledge_non_list_payload(mock_settings: KnowledgeServerSettings) -> None:
    """search_knowledge returns empty tuple when response is not a list."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=_create_mock_response(200, {"unexpected": "dict"}))

    repo = SupabaseKnowledgeRepository(settings=mock_settings, http_client=mock_client)
    results = await repo.search_knowledge(KnowledgeSearchCriteriaDTO(query_text="test"))
    assert results == ()


@pytest.mark.asyncio
async def test_get_runbook_success(mock_settings: KnowledgeServerSettings) -> None:
    """get_runbook retrieves and maps operational runbook."""
    raw_payload = [
        {
            "runbook_id": "RB-AUTH-01",
            "title": "SAML Signing Certificate Expiry",
            "problem_description": "Users receive 401 due to expired IdP certificate.",
            "diagnostic_steps": "Check token expiry in logs\nInspect IdP metadata",
            "remediation_steps": "Import updated certificate in Admin\nRestart pool",
            "product": "SuperOffice CRM",
            "verified_version": "10.2",
            "last_reviewed": "2026-08-15T12:00:00Z",
            "source_reference": "RB-AUTH-01",
        }
    ]
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=_create_mock_response(200, raw_payload))

    repo = SupabaseKnowledgeRepository(settings=mock_settings, http_client=mock_client)
    runbook = await repo.get_runbook("RB-AUTH-01")

    assert runbook.runbook_id == "RB-AUTH-01"
    assert runbook.title == "SAML Signing Certificate Expiry"
    assert len(runbook.diagnostic_steps) == 2
    assert len(runbook.remediation_steps) == 2
    assert runbook.last_reviewed == datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_get_runbook_not_found(mock_settings: KnowledgeServerSettings) -> None:
    """get_runbook raises RunbookNotFoundError when response is empty or 404."""
    # 1. Empty list response
    mock_client_empty = AsyncMock(spec=httpx.AsyncClient)
    mock_client_empty.get = AsyncMock(return_value=_create_mock_response(200, []))

    repo = SupabaseKnowledgeRepository(settings=mock_settings, http_client=mock_client_empty)
    with pytest.raises(RunbookNotFoundError) as exc_info:
        await repo.get_runbook("RB-MISSING-01")
    assert "RB-MISSING-01" in str(exc_info.value)

    # 2. 404 response
    mock_client_404 = AsyncMock(spec=httpx.AsyncClient)
    mock_client_404.get = AsyncMock(return_value=_create_mock_response(404, {"error": "Not found"}))

    repo_404 = SupabaseKnowledgeRepository(settings=mock_settings, http_client=mock_client_404)
    with pytest.raises(RunbookNotFoundError):
        await repo_404.get_runbook("RB-MISSING-02")


@pytest.mark.asyncio
async def test_find_known_issues_success(mock_settings: KnowledgeServerSettings) -> None:
    """find_known_issues maps matching known issues."""
    raw_payload = [
        {
            "issue_id": "KI-SO-8821",
            "title": "Token Refresh Race Condition",
            "symptom_summary": "Intermittent 401 on background worker requests.",
            "root_cause_summary": "Token invalidated before new token persisted.",
            "workaround": "Increase sliding window in Admin.",
            "permanent_fix_reference": "SuperOffice 10.2.3",
            "affected_products": "SuperOffice CRM, Service",
            "affected_versions": "10.2.0, 10.2.1",
            "category": "authentication",
            "source_reference": "KI-SO-8821",
        }
    ]
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=_create_mock_response(200, raw_payload))

    repo = SupabaseKnowledgeRepository(settings=mock_settings, http_client=mock_client)
    issues = await repo.find_known_issues(
        KnownIssueSearchCriteriaDTO(query_text="Token Refresh", category="authentication")
    )

    assert len(issues) == 1
    assert issues[0].issue_id == "KI-SO-8821"
    assert issues[0].affected_products == ("SuperOffice CRM", "Service")
    assert issues[0].affected_versions == ("10.2.0", "10.2.1")
    assert issues[0].workaround == "Increase sliding window in Admin."


@pytest.mark.asyncio
async def test_find_known_issues_non_list_payload(mock_settings: KnowledgeServerSettings) -> None:
    """find_known_issues returns empty tuple when response is not a list."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=_create_mock_response(200, {"unexpected": "dict"}))

    repo = SupabaseKnowledgeRepository(settings=mock_settings, http_client=mock_client)
    issues = await repo.find_known_issues(KnownIssueSearchCriteriaDTO())
    assert issues == ()


@pytest.mark.asyncio
async def test_unconfigured_client_fails_closed(mock_settings: KnowledgeServerSettings) -> None:
    """Repository fails closed cleanly with KNOWLEDGE_CLIENT_NOT_CONFIGURED when client is None."""
    repo = SupabaseKnowledgeRepository(settings=mock_settings, http_client=None)

    with pytest.raises(KnowledgeSearchError) as exc_search:
        await repo.search_knowledge(KnowledgeSearchCriteriaDTO(query_text="test"))
    assert exc_search.value.error_code == "KNOWLEDGE_CLIENT_NOT_CONFIGURED"

    with pytest.raises(KnowledgeSearchError) as exc_rb:
        await repo.get_runbook("RB-01")
    assert exc_rb.value.error_code == "KNOWLEDGE_CLIENT_NOT_CONFIGURED"

    with pytest.raises(KnowledgeSearchError) as exc_ki:
        await repo.find_known_issues(KnownIssueSearchCriteriaDTO())
    assert exc_ki.value.error_code == "KNOWLEDGE_CLIENT_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_unconfigured_backend_mappings_fail_closed(
    unconfigured_settings: KnowledgeServerSettings,
) -> None:
    """Repository fails closed when backend mappings are None (KNOWLEDGE_BACKEND_NOT_CONFIGURED)."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    repo = SupabaseKnowledgeRepository(settings=unconfigured_settings, http_client=mock_client)

    with pytest.raises(KnowledgeSearchError) as exc_search:
        await repo.search_knowledge(KnowledgeSearchCriteriaDTO(query_text="test"))
    assert exc_search.value.error_code == "KNOWLEDGE_BACKEND_NOT_CONFIGURED"

    with pytest.raises(KnowledgeSearchError) as exc_rb:
        await repo.get_runbook("RB-01")
    assert exc_rb.value.error_code == "KNOWLEDGE_BACKEND_NOT_CONFIGURED"

    with pytest.raises(KnowledgeSearchError) as exc_ki:
        await repo.find_known_issues(KnownIssueSearchCriteriaDTO())
    assert exc_ki.value.error_code == "KNOWLEDGE_BACKEND_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_error_sanitization_strips_urls_and_keys(
    mock_settings: KnowledgeServerSettings,
) -> None:
    """Errors sanitize backend URLs, API keys, and authorization headers."""
    secret_url = "https://sensitive-corp.supabase.co/rest/v1/rpc/match_documents"
    raw_error = f"Connection failed to {secret_url} with apikey=super-secret-key-1234567890"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(side_effect=Exception(raw_error))

    repo = SupabaseKnowledgeRepository(settings=mock_settings, http_client=mock_client)

    with pytest.raises(KnowledgeSearchError) as exc_info:
        await repo.search_knowledge(KnowledgeSearchCriteriaDTO(query_text="test query"))

    msg = str(exc_info.value)
    assert "https://sensitive-corp.supabase.co" not in msg
    assert "super-secret-key-1234567890" not in msg
    assert "[ENDPOINT_REDACTED]" in msg
    assert "[KEY_REDACTED]" in msg


@pytest.mark.asyncio
async def test_timeout_and_auth_error_translations(
    mock_settings: KnowledgeServerSettings,
) -> None:
    """HTTP timeout and auth failures map to typed KnowledgeSearchError codes."""
    # 1. Timeout mapping
    mock_client_timeout = AsyncMock(spec=httpx.AsyncClient)
    mock_client_timeout.post = AsyncMock(side_effect=httpx.TimeoutException("Read timeout"))

    repo_timeout = SupabaseKnowledgeRepository(
        settings=mock_settings, http_client=mock_client_timeout
    )
    with pytest.raises(KnowledgeSearchError) as exc_to:
        await repo_timeout.search_knowledge(KnowledgeSearchCriteriaDTO(query_text="test"))
    assert exc_to.value.error_code == "KNOWLEDGE_TIMEOUT"

    # 2. Auth failure mapping (401)
    mock_client_auth = AsyncMock(spec=httpx.AsyncClient)
    mock_client_auth.post = AsyncMock(
        return_value=_create_mock_response(401, {"error": "Invalid API key"})
    )

    repo_auth = SupabaseKnowledgeRepository(settings=mock_settings, http_client=mock_client_auth)
    with pytest.raises(KnowledgeSearchError) as exc_auth:
        await repo_auth.search_knowledge(KnowledgeSearchCriteriaDTO(query_text="test"))
    assert exc_auth.value.error_code == "KNOWLEDGE_AUTH_FAILURE"
