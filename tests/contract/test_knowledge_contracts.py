"""Offline contract tests for Knowledge / Supabase semantic retrieval boundaries and fakes."""

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnowledgeSearchResultDomainDTO,
    KnownIssueDomainDTO,
    KnownIssueSearchCriteriaDTO,
    MinimizedKnowledgeChunkDTO,
    MinimizedKnownIssueDTO,
    MinimizedRunbookDTO,
    RunbookDetailDomainDTO,
)
from kb_mcp.contracts.errors import (
    KnowledgeSearchError,
    RunbookNotFoundError,
)
from kb_mcp.contracts.interfaces import (
    KnowledgeRepository,
)
from tests.fakes.fake_knowledge_repository import FakeKnowledgeRepository

# ============================================================================
# 1. DTO Validation & Immutability Tests
# ============================================================================


def test_knowledge_search_result_dto_valid() -> None:
    """Verify KnowledgeSearchResultDomainDTO initialization with valid attributes."""
    doc = KnowledgeSearchResultDomainDTO(
        document_id="DOC-AUTH-101",
        title="SuperOffice Active Directory Federation Guide",
        content_excerpt="Configure ADFS claims provider trust and certificate rollover.",
        category="authentication",
        product="SuperOffice CRM",
        version="10.2",
        tags=("adfs", "sso", "identity"),
        relevance_score=0.92,
        source_reference="KB-AUTH-ADFS",
    )
    assert doc.document_id == "DOC-AUTH-101"
    assert doc.relevance_score == 0.92
    assert "sso" in doc.tags


def test_knowledge_dto_immutability_and_extra_forbid() -> None:
    """Verify knowledge DTOs are frozen and forbid extra unapproved fields."""
    doc = KnowledgeSearchResultDomainDTO(
        document_id="DOC-001",
        title="Sample Title",
        content_excerpt="Sample Excerpt",
        category="troubleshooting",
        relevance_score=0.85,
        source_reference="REF-001",
    )
    # Frozen mutation check
    field_to_mutate = "relevance_score"
    with pytest.raises(ValidationError):
        setattr(doc, field_to_mutate, 0.99)

    # Extra field forbid check
    extra_payload = {
        "document_id": "DOC-002",
        "title": "Extra Field Test",
        "content_excerpt": "Valid excerpt",
        "category": "database",
        "relevance_score": 0.75,
        "source_reference": "REF-002",
        "unauthorized_embedding_vector": [0.12, 0.44, 0.88],
    }
    with pytest.raises(ValidationError):
        KnowledgeSearchResultDomainDTO.model_validate(extra_payload)


def test_criteria_validation_bounds() -> None:
    """Verify validation constraints on criteria DTOs."""
    # query_text too short (< 2 chars)
    with pytest.raises(ValidationError):
        KnowledgeSearchCriteriaDTO(query_text="a")

    # limit out of bounds (le=0 or >50)
    with pytest.raises(ValidationError):
        KnowledgeSearchCriteriaDTO(query_text="valid query", limit=0)
    with pytest.raises(ValidationError):
        KnowledgeSearchCriteriaDTO(query_text="valid query", limit=51)

    # min_relevance_score out of range (< 0.0 or > 1.0)
    with pytest.raises(ValidationError):
        KnowledgeSearchCriteriaDTO(query_text="valid query", min_relevance_score=1.5)


def test_ai_facing_dto_separation() -> None:
    """Verify AI-facing minimized DTOs expose safe sanitized models."""
    chunk = MinimizedKnowledgeChunkDTO(
        document_id="DOC-99",
        title="Database Maintenance Window SOP",
        content_excerpt="Verify replica synchronization status before index defragmentation.",
        category="runbook",
        relevance_score=0.88,
        source_reference="RB-DB-001",
    )
    assert chunk.document_id == "DOC-99"
    assert "source_reference" in MinimizedKnowledgeChunkDTO.model_fields

    runbook = MinimizedRunbookDTO(
        runbook_id="RB-MAIL-02",
        title="Mailgun Outbound Delivery Troubleshooting",
        problem_description="Emails queued but not delivered to customer inbox.",
        diagnostic_steps=("Check SMTP queue status", "Verify SPF and DKIM records"),
        remediation_steps=("Flush stuck queue", "Rotate SMTP service credential"),
        source_reference="RB-MAIL-02",
    )
    assert runbook.runbook_id == "RB-MAIL-02"
    assert len(runbook.diagnostic_steps) == 2

    known_issue = MinimizedKnownIssueDTO(
        issue_id="KI-SO-9921",
        title="Intermittent 401 on REST WebAPI during token refresh",
        symptom_summary="Session expires abruptly when background worker refreshes token.",
        workaround="Increase refresh token sliding expiration window in SuperOffice Admin.",
        source_reference="KI-SO-9921",
    )
    assert known_issue.issue_id == "KI-SO-9921"


# ============================================================================
# 2. Error Sanitization Tests
# ============================================================================


def test_knowledge_search_error_sanitization() -> None:
    """Verify KnowledgeSearchError sanitizes backend Supabase connection details."""
    secret_url = (
        "https://xyzcompany.supabase.co/rest/v1/rpc/match_documents?apikey=super-secret-key"
    )
    err = KnowledgeSearchError(
        "Failed to query vector similarity store.",
        details={"endpoint": secret_url, "vector_dim": 1536},
    )
    sanitized = err.to_sanitized_dict()
    assert sanitized["error"] == "KNOWLEDGE_SEARCH_ERROR"
    assert sanitized["message"] == "Failed to query vector similarity store."
    assert "super-secret-key" not in sanitized.get("message", "")


def test_runbook_not_found_error() -> None:
    """Verify RunbookNotFoundError formats cleanly without leaking stack traces."""
    err = RunbookNotFoundError("RB-NONEXISTENT-99")
    assert err.error_code == "RESOURCE_NOT_FOUND"
    assert "RB-NONEXISTENT-99" in err.message


# ============================================================================
# 3. FakeKnowledgeRepository & Protocol Conformance Tests
# ============================================================================


def test_fake_knowledge_repository_is_instance_of_protocol() -> None:
    """Verify FakeKnowledgeRepository satisfies KnowledgeRepository Protocol."""
    fake = FakeKnowledgeRepository()
    assert isinstance(fake, KnowledgeRepository)


def test_fake_knowledge_repository_search_and_ranking() -> None:
    """Verify deterministic ranking and metadata filtering in FakeKnowledgeRepository."""

    async def _run_async() -> None:
        fake = FakeKnowledgeRepository()

        # 1. Seed sanitized documentation chunks
        fake.seed_document(
            KnowledgeSearchResultDomainDTO(
                document_id="DOC-1",
                title="SuperOffice SSO SAML Configuration",
                content_excerpt="Steps to configure Okta SSO with SuperOffice Web.",
                category="authentication",
                product="SuperOffice CRM",
                version="10.2",
                tags=("sso", "saml", "okta"),
                relevance_score=0.95,
                source_reference="DOC-1",
            )
        )
        fake.seed_document(
            KnowledgeSearchResultDomainDTO(
                document_id="DOC-2",
                title="Database Replication Latency Troubleshooting",
                content_excerpt="Investigate AlwaysOn availability group replica sync delays.",
                category="database",
                product="SuperOffice Database",
                version="10.2",
                tags=("mssql", "alwayson", "replication"),
                relevance_score=0.82,
                source_reference="DOC-2",
            )
        )
        fake.seed_document(
            KnowledgeSearchResultDomainDTO(
                document_id="DOC-3",
                title="Legacy SAML v1 Migration",
                content_excerpt="Upgrading from SAML 1.1 to modern SAML 2.0.",
                category="authentication",
                product="SuperOffice CRM",
                version="9.1",
                tags=("sso", "saml", "legacy"),
                relevance_score=0.60,
                source_reference="DOC-3",
            )
        )

        # 2. Search by query text and verify deterministic descending score ranking
        res1 = await fake.search_knowledge(
            KnowledgeSearchCriteriaDTO(query_text="SAML SSO", limit=5)
        )
        assert len(res1) == 2
        assert res1[0].document_id == "DOC-1"
        assert res1[0].relevance_score >= res1[1].relevance_score

        # 3. Filter by category and version
        res2 = await fake.search_knowledge(
            KnowledgeSearchCriteriaDTO(
                query_text="SAML",
                category="authentication",
                version="10.2",
            )
        )
        assert len(res2) == 1
        assert res2[0].document_id == "DOC-1"

        # 4. Filter by minimum relevance score threshold
        res3 = await fake.search_knowledge(
            KnowledgeSearchCriteriaDTO(
                query_text="SAML",
                min_relevance_score=0.90,
            )
        )
        assert len(res3) == 1
        assert res3[0].document_id == "DOC-1"

        # 5. Empty search results
        res_empty = await fake.search_knowledge(
            KnowledgeSearchCriteriaDTO(query_text="nonexistent keyword XYZ12345")
        )
        assert len(res_empty) == 0

    asyncio.run(_run_async())


def test_fake_knowledge_repository_runbook_retrieval_and_not_found() -> None:
    """Verify successful runbook retrieval and missing runbook error handling."""

    async def _run_async() -> None:
        fake = FakeKnowledgeRepository()
        now = datetime.now(UTC)

        fake.seed_runbook(
            RunbookDetailDomainDTO(
                runbook_id="RB-SSO-01",
                title="SSO Certificate Expiry Remediation",
                problem_description="IdP signing certificate has expired, blocking user logins.",
                diagnostic_steps=(
                    "Check SuperOffice identity log for SEC-401 error",
                    "Verify token signing certificate validity in IdP metadata",
                ),
                remediation_steps=(
                    "Import renewed public certificate in SuperOffice Admin",
                    "Recycle IIS Application Pool",
                ),
                product="SuperOffice CRM",
                verified_version="10.2",
                last_reviewed=now,
                source_reference="RB-SSO-01",
            )
        )

        # 1. Successful runbook retrieval
        runbook = await fake.get_runbook("RB-SSO-01")
        assert runbook.runbook_id == "RB-SSO-01"
        assert runbook.title == "SSO Certificate Expiry Remediation"
        assert len(runbook.diagnostic_steps) == 2
        assert len(runbook.remediation_steps) == 2

        # 2. Missing runbook raises RunbookNotFoundError
        with pytest.raises(RunbookNotFoundError) as exc_info:
            await fake.get_runbook("RB-NONEXISTENT-88")
        assert "RB-NONEXISTENT-88" in str(exc_info.value)

    asyncio.run(_run_async())


def test_fake_knowledge_repository_known_issues_matching_and_empty() -> None:
    """Verify known issues retrieval, metadata filtering, and empty result handling."""

    async def _run_async() -> None:
        fake = FakeKnowledgeRepository()

        fake.seed_known_issue(
            KnownIssueDomainDTO(
                issue_id="KI-AUTH-004",
                title="AAD Token Expiration during long document edits",
                symptom_summary="Users receive 401 Unauthorized while editing long documents.",
                root_cause_summary="Access token lifetime expires before auto-save executes.",
                workaround="Enable silent refresh in SuperOffice client preferences.",
                permanent_fix_reference="SuperOffice 10.2.4 Hotfix 2",
                affected_products=("SuperOffice CRM",),
                affected_versions=("10.2.0", "10.2.1", "10.2.2"),
                category="authentication",
                source_reference="KI-AUTH-004",
            )
        )

        # 1. Successful match by query text and product
        issues = await fake.find_known_issues(
            KnownIssueSearchCriteriaDTO(query_text="Token Expiration", product="SuperOffice CRM")
        )
        assert len(issues) == 1
        assert issues[0].issue_id == "KI-AUTH-004"
        assert issues[0].workaround is not None

        # 2. Filter by category
        cat_issues = await fake.find_known_issues(
            KnownIssueSearchCriteriaDTO(category="authentication")
        )
        assert len(cat_issues) == 1

        # 3. Empty matches when no known issues match criteria
        empty_issues = await fake.find_known_issues(
            KnownIssueSearchCriteriaDTO(query_text="nonexistent issue ABC999")
        )
        assert len(empty_issues) == 0

        # 4. Simulated failure check
        fake.set_should_fail(True)
        with pytest.raises(KnowledgeSearchError):
            await fake.find_known_issues(KnownIssueSearchCriteriaDTO())

    asyncio.run(_run_async())
