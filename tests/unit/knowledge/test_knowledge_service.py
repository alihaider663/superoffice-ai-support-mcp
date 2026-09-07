"""Unit tests for KnowledgeApplicationService minimization and PII redaction."""

from datetime import UTC, datetime

import pytest

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
from kb_mcp.services.knowledge_service import KnowledgeApplicationService
from platform_security.sanitization import RecursiveOutputSanitizer
from tests.fakes.fake_knowledge_repository import FakeKnowledgeRepository


@pytest.fixture
def fake_repo() -> FakeKnowledgeRepository:
    """Provide a seeded FakeKnowledgeRepository for service testing."""
    repo = FakeKnowledgeRepository()
    now = datetime.now(UTC)

    repo.seed_document(
        KnowledgeSearchResultDomainDTO(
            document_id="DOC-101",
            title="SuperOffice SSO with Okta admin@example.com",
            content_excerpt="Contact support at john.doe@superoffice.no or +47 22 33 44 55.",
            category="authentication",
            product="SuperOffice CRM",
            version="10.2",
            tags=("sso", "okta", "auth"),
            relevance_score=0.94,
            source_reference="KB-AUTH-101",
        )
    )

    repo.seed_runbook(
        RunbookDetailDomainDTO(
            runbook_id="RB-MAIL-01",
            title="Mailgun Service Outage for admin@customer.com",
            problem_description=(
                "Customer alice@company.org reported email failure "
                "with key sk_live_1234567890abcdef."
            ),
            diagnostic_steps=(
                "Check error logs for contact support@provider.com",
                "Verify API token Bearer abc.def.ghi",
            ),
            remediation_steps=(
                "Rotate token and contact admin@superoffice.no",
                "Restart service pool",
            ),
            product="SuperOffice Customer Service",
            verified_version="10.2",
            last_reviewed=now,
            source_reference="RB-MAIL-01",
        )
    )

    repo.seed_known_issue(
        KnownIssueDomainDTO(
            issue_id="KI-SO-101",
            title="SAML Assertion Timeout for user@domain.com",
            symptom_summary="Error on login: token expired for user support@partner.com",
            root_cause_summary="Clock skew exceeds IdP threshold",
            workaround="Adjust skew allowance in SuperOffice Admin or email dba@customer.com",
            permanent_fix_reference="SuperOffice 10.2 Hotfix 1",
            affected_products=("SuperOffice CRM",),
            affected_versions=("10.2.0",),
            category="authentication",
            source_reference="KI-SO-101",
        )
    )

    return repo


@pytest.mark.asyncio
async def test_search_knowledge_minimization_and_pii_redaction(
    fake_repo: FakeKnowledgeRepository,
) -> None:
    """search_knowledge projects MinimizedKnowledgeChunkDTO and scrubs PII from text."""
    service = KnowledgeApplicationService(repository=fake_repo)

    results = await service.search_knowledge(
        KnowledgeSearchCriteriaDTO(query_text="SuperOffice SSO")
    )
    assert len(results) == 1
    chunk = results[0]

    # Verify DTO type
    assert isinstance(chunk, MinimizedKnowledgeChunkDTO)
    assert chunk.document_id == "DOC-101"
    assert chunk.category == "authentication"
    assert chunk.relevance_score == 0.94
    assert chunk.source_reference == "KB-AUTH-101"

    # Verify PII scrubbing on title and content excerpt
    assert "admin@example.com" not in chunk.title
    assert "[REDACTED_EMAIL]" in chunk.title
    assert "john.doe@superoffice.no" not in chunk.content_excerpt
    assert "+47 22 33 44 55" not in chunk.content_excerpt
    assert "[REDACTED_EMAIL]" in chunk.content_excerpt
    assert "[REDACTED_PHONE]" in chunk.content_excerpt

    # Verify internal domain fields are not present on minimized DTO
    assert not hasattr(chunk, "tags")
    assert not hasattr(chunk, "product")
    assert not hasattr(chunk, "version")


@pytest.mark.asyncio
async def test_get_runbook_minimization_and_pii_redaction(
    fake_repo: FakeKnowledgeRepository,
) -> None:
    """get_runbook projects MinimizedRunbookDTO and scrubs PII/secrets from all text steps."""
    service = KnowledgeApplicationService(repository=fake_repo)

    runbook = await service.get_runbook("RB-MAIL-01")
    assert isinstance(runbook, MinimizedRunbookDTO)
    assert runbook.runbook_id == "RB-MAIL-01"
    assert runbook.source_reference == "RB-MAIL-01"

    # Verify secret and PII redaction
    assert "admin@customer.com" not in runbook.title
    assert "alice@company.org" not in runbook.problem_description
    assert "sk_live_1234567890abcdef" not in runbook.problem_description
    assert "[REDACTED_API_KEY]" in runbook.problem_description

    # Diagnostic steps redaction
    assert "support@provider.com" not in runbook.diagnostic_steps[0]
    assert "[REDACTED_EMAIL]" in runbook.diagnostic_steps[0]

    # Remediation steps redaction
    assert "admin@superoffice.no" not in runbook.remediation_steps[0]
    assert "[REDACTED_EMAIL]" in runbook.remediation_steps[0]

    # Internal fields excluded
    assert not hasattr(runbook, "product")
    assert not hasattr(runbook, "verified_version")
    assert not hasattr(runbook, "last_reviewed")


@pytest.mark.asyncio
async def test_get_runbook_not_found(fake_repo: FakeKnowledgeRepository) -> None:
    """get_runbook raises RunbookNotFoundError when ID is missing."""
    service = KnowledgeApplicationService(repository=fake_repo)

    with pytest.raises(RunbookNotFoundError) as exc_info:
        await service.get_runbook("RB-NONEXISTENT-99")

    assert "RB-NONEXISTENT-99" in str(exc_info.value)
    assert exc_info.value.error_code == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_find_known_issues_minimization_and_pii_redaction(
    fake_repo: FakeKnowledgeRepository,
) -> None:
    """find_known_issues projects MinimizedKnownIssueDTO and scrubs PII from symptom/workaround."""
    service = KnowledgeApplicationService(repository=fake_repo)

    issues = await service.find_known_issues(KnownIssueSearchCriteriaDTO(query_text="SAML"))
    assert len(issues) == 1
    issue = issues[0]

    assert isinstance(issue, MinimizedKnownIssueDTO)
    assert issue.issue_id == "KI-SO-101"
    assert issue.source_reference == "KI-SO-101"

    # Verify PII scrubbing
    assert "user@domain.com" not in issue.title
    assert "support@partner.com" not in issue.symptom_summary
    assert "[REDACTED_EMAIL]" in issue.symptom_summary
    assert issue.workaround is not None
    assert "dba@customer.com" not in issue.workaround
    assert "[REDACTED_EMAIL]" in issue.workaround

    # Internal fields excluded
    assert not hasattr(issue, "root_cause_summary")
    assert not hasattr(issue, "permanent_fix_reference")
    assert not hasattr(issue, "affected_products")
    assert not hasattr(issue, "affected_versions")
    assert not hasattr(issue, "category")


@pytest.mark.asyncio
async def test_empty_search_and_issues_returns_empty_tuple(
    fake_repo: FakeKnowledgeRepository,
) -> None:
    """Service returns empty tuples on empty repository results without errors."""
    service = KnowledgeApplicationService(repository=fake_repo)

    empty_docs = await service.search_knowledge(
        KnowledgeSearchCriteriaDTO(query_text="nonexistent keyword ZZZZZ")
    )
    assert empty_docs == ()

    empty_issues = await service.find_known_issues(
        KnownIssueSearchCriteriaDTO(query_text="nonexistent error code 99999")
    )
    assert empty_issues == ()


@pytest.mark.asyncio
async def test_service_propagates_repository_errors(
    fake_repo: FakeKnowledgeRepository,
) -> None:
    """Service propagates KnowledgeSearchError without swallowing."""
    fake_repo.set_should_fail(True)
    service = KnowledgeApplicationService(repository=fake_repo)

    with pytest.raises(KnowledgeSearchError):
        await service.search_knowledge(KnowledgeSearchCriteriaDTO(query_text="anything"))

    with pytest.raises(KnowledgeSearchError):
        await service.get_runbook("RB-MAIL-01")

    with pytest.raises(KnowledgeSearchError):
        await service.find_known_issues(KnownIssueSearchCriteriaDTO())


@pytest.mark.asyncio
async def test_service_custom_sanitizer_injection(fake_repo: FakeKnowledgeRepository) -> None:
    """Service accepts custom RecursiveOutputSanitizer injection."""
    custom_sanitizer = RecursiveOutputSanitizer()
    service = KnowledgeApplicationService(repository=fake_repo, sanitizer=custom_sanitizer)
    assert service._sanitize_string("") == ""
    assert service._sanitize_string(None) == ""
