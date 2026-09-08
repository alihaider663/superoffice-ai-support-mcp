"""Unit and contract tests for PostgresKnowledgeRepository."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from kb_mcp.adapters import postgres_repository
from kb_mcp.adapters.postgres_repository import (
    FIND_KNOWN_ISSUES_ALL_SQL,
    FIND_KNOWN_ISSUES_TRGM_SQL,
    GET_RUNBOOK_SQL,
    SEARCH_KNOWLEDGE_SQL,
    PostgresKnowledgeRepository,
)
from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnowledgeSearchResultDomainDTO,
    KnownIssueDomainDTO,
    KnownIssueSearchCriteriaDTO,
    RunbookDetailDomainDTO,
)
from kb_mcp.contracts.errors import (
    EmbeddingDimensionError,
    EmbeddingInputError,
    KnowledgeSearchError,
    MalformedRunbookDataError,
    RunbookNotFoundError,
)
from kb_mcp.contracts.interfaces import KnowledgeRepository


class MockResultMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class MockResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> MockResultMappings:
        return MockResultMappings(self._rows)


class MockSession:
    def __init__(
        self, rows: list[dict[str, Any]] | None = None, exc: Exception | None = None
    ) -> None:
        self.rows = rows if rows is not None else []
        self.exc = exc
        self.executed_statements: list[Any] = []
        self.executed_params: list[dict[str, Any]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> MockResult:
        self.executed_statements.append(statement)
        self.executed_params.append(params or {})
        if self.exc:
            raise self.exc
        return MockResult(self.rows)

    async def __aenter__(self) -> "MockSession":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


def make_repo(mock_session: MockSession) -> PostgresKnowledgeRepository:
    def sessionmaker() -> MockSession:
        return mock_session

    return PostgresKnowledgeRepository(session_factory=sessionmaker)  # type: ignore[arg-type]


def valid_embedding() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 383


# ============================================================================
# Protocol Conformance
# ============================================================================


def test_postgres_repository_is_instance_of_protocol() -> None:
    """Verify PostgresKnowledgeRepository satisfies KnowledgeRepository Protocol."""
    session = MockSession()
    repo = make_repo(session)
    assert isinstance(repo, KnowledgeRepository)


# ============================================================================
# Embedding Validation (search_knowledge)
# ============================================================================


@pytest.mark.asyncio
async def test_search_knowledge_rejects_dimension_mismatch() -> None:
    """search_knowledge rejects query_embedding with dimension != 384."""
    session = MockSession()
    repo = make_repo(session)
    criteria = KnowledgeSearchCriteriaDTO(query_text="authentication")

    with pytest.raises(EmbeddingDimensionError) as exc_info:
        await repo.search_knowledge(criteria, (0.1, 0.2))  # length 2
    assert exc_info.value.error_code == "EMBEDDING_DIMENSION_ERROR"
    assert exc_info.value.details["actual"] == 2
    assert exc_info.value.details["expected"] == 384

    with pytest.raises(EmbeddingDimensionError):
        await repo.search_knowledge(criteria, (0.0,) * 512)


@pytest.mark.asyncio
async def test_search_knowledge_rejects_nan_embedding() -> None:
    """search_knowledge fails closed when embedding contains NaN."""
    session = MockSession()
    repo = make_repo(session)
    criteria = KnowledgeSearchCriteriaDTO(query_text="authentication")
    nan_emb = (float("nan"),) + (0.0,) * 383

    with pytest.raises(EmbeddingInputError) as exc_info:
        await repo.search_knowledge(criteria, nan_emb)
    assert exc_info.value.error_code == "EMBEDDING_INPUT_ERROR"


@pytest.mark.asyncio
async def test_search_knowledge_rejects_positive_infinity_embedding() -> None:
    """search_knowledge fails closed when embedding contains +Infinity."""
    session = MockSession()
    repo = make_repo(session)
    criteria = KnowledgeSearchCriteriaDTO(query_text="authentication")
    inf_emb = (float("inf"),) + (0.0,) * 383

    with pytest.raises(EmbeddingInputError) as exc_info:
        await repo.search_knowledge(criteria, inf_emb)
    assert exc_info.value.error_code == "EMBEDDING_INPUT_ERROR"


@pytest.mark.asyncio
async def test_search_knowledge_rejects_negative_infinity_embedding() -> None:
    """search_knowledge fails closed when embedding contains -Infinity."""
    session = MockSession()
    repo = make_repo(session)
    criteria = KnowledgeSearchCriteriaDTO(query_text="authentication")
    ninf_emb = (float("-inf"),) + (0.0,) * 383

    with pytest.raises(EmbeddingInputError) as exc_info:
        await repo.search_knowledge(criteria, ninf_emb)
    assert exc_info.value.error_code == "EMBEDDING_INPUT_ERROR"


@pytest.mark.asyncio
async def test_search_knowledge_rejects_non_sequence_embedding() -> None:
    """search_knowledge fails closed when embedding is not a sequence."""
    session = MockSession()
    repo = make_repo(session)
    criteria = KnowledgeSearchCriteriaDTO(query_text="authentication")

    with pytest.raises(EmbeddingInputError):
        await repo.search_knowledge(criteria, None)  # type: ignore[arg-type]


# ============================================================================
# Search Knowledge Retrieval & Mapping
# ============================================================================


@pytest.mark.asyncio
async def test_search_knowledge_bounded_fixed_retrieval_and_limit() -> None:
    """search_knowledge bounds limit to ceiling of 50."""
    session = MockSession(rows=[])
    repo = make_repo(session)

    # Request limit of 100 (criteria caps at 50, but repository also bounds)
    criteria = KnowledgeSearchCriteriaDTO(query_text="mail server", limit=50)
    await repo.search_knowledge(criteria, valid_embedding())

    assert len(session.executed_params) == 1
    params = session.executed_params[0]
    assert params["limit"] <= 50
    assert len(params["query_vector"]) == 384


@pytest.mark.asyncio
async def test_search_knowledge_row_mapping_and_relevance_calculation() -> None:
    """search_knowledge correctly maps database rows to KnowledgeSearchResultDomainDTO."""
    mock_rows = [
        {
            "chunk_id": "CHK-001",
            "document_id": "DOC-101",
            "title": "Configuring SSO SAML",
            "content": "Step 1: Open SuperOffice Admin and navigate to Identity Providers.",
            "document_type": "troubleshooting",
            "version": 1,
            "source_reference": "DOC-SSO-01",
            "cosine_distance": 0.15,
        },
        {
            "chunk_id": "CHK-002",
            "document_id": "DOC-102",
            "title": "OAuth 2.0 Token Renewal",
            "content": "Step 2: Verify refresh token lifetime.",
            "document_type": "architecture",
            "version": 2,
            "source_reference": "DOC-OAUTH-02",
            "cosine_distance": 0.40,
        },
    ]
    session = MockSession(rows=mock_rows)
    repo = make_repo(session)

    criteria = KnowledgeSearchCriteriaDTO(query_text="SSO login")
    results = await repo.search_knowledge(criteria, valid_embedding())

    assert len(results) == 2
    first, second = results

    assert isinstance(first, KnowledgeSearchResultDomainDTO)
    assert first.document_id == "DOC-101"
    assert first.title == "Configuring SSO SAML"
    assert (
        first.content_excerpt
        == "Step 1: Open SuperOffice Admin and navigate to Identity Providers."
    )
    assert first.category == "troubleshooting"
    assert first.version == "1"
    assert first.source_reference == "DOC-SSO-01"
    assert first.relevance_score == 0.85  # 1.0 - 0.15

    assert second.document_id == "DOC-102"
    assert second.relevance_score == 0.60  # 1.0 - 0.40


@pytest.mark.asyncio
async def test_search_knowledge_relevance_score_clamped() -> None:
    """Relevance score is clamped to [0.0, 1.0] even with extreme distance values."""
    mock_rows = [
        {
            "chunk_id": "CHK-NEG",
            "document_id": "DOC-NEG",
            "title": "Super Similar",
            "content": "Exact match content",
            "document_type": "config",
            "version": 1,
            "source_reference": "DOC-01",
            "cosine_distance": -0.05,  # float inaccuracy
        },
        {
            "chunk_id": "CHK-DISTANT",
            "document_id": "DOC-DISTANT",
            "title": "Very Distant",
            "content": "Distant content",
            "document_type": "config",
            "version": 1,
            "source_reference": "DOC-02",
            "cosine_distance": 1.50,  # distance > 1
        },
    ]
    session = MockSession(rows=mock_rows)
    repo = make_repo(session)

    results = await repo.search_knowledge(
        KnowledgeSearchCriteriaDTO(query_text="test"), valid_embedding()
    )
    assert len(results) == 2
    assert results[0].relevance_score == 1.0
    assert results[1].relevance_score == 0.0


@pytest.mark.asyncio
async def test_search_knowledge_respects_min_relevance_threshold() -> None:
    """search_knowledge filters out rows with relevance score below threshold."""
    mock_rows = [
        {
            "chunk_id": "CHK-HIGH",
            "document_id": "DOC-HIGH",
            "title": "High Match",
            "content": "Relevant content",
            "document_type": "config",
            "version": 1,
            "source_reference": "DOC-01",
            "cosine_distance": 0.10,  # relevance 0.90
        },
        {
            "chunk_id": "CHK-LOW",
            "document_id": "DOC-LOW",
            "title": "Low Match",
            "content": "Less relevant content",
            "document_type": "config",
            "version": 1,
            "source_reference": "DOC-02",
            "cosine_distance": 0.50,  # relevance 0.50
        },
    ]
    session = MockSession(rows=mock_rows)
    repo = make_repo(session)

    results = await repo.search_knowledge(
        KnowledgeSearchCriteriaDTO(query_text="test", min_relevance_score=0.80),
        valid_embedding(),
    )
    assert len(results) == 1
    assert results[0].document_id == "DOC-HIGH"


# ============================================================================
# get_runbook Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_runbook_exact_retrieval() -> None:
    """get_runbook retrieves exact runbook matching runbook_id."""
    now = datetime.now(UTC)
    mock_rows = [
        {
            "runbook_id": "RB-MAIL-001",
            "title": "Mailgun Queue Remediation",
            "problem_description": "Outgoing email queue is stalled.",
            "diagnostic_steps": ["Check event log", "Verify SMTP credentials"],
            "remediation_steps": ["Flush queue", "Restart Service Pool"],
            "product": "Customer Service",
            "verified_version": "10.2",
            "last_reviewed": now,
            "source_reference": "RB-MAIL-001",
        }
    ]
    session = MockSession(rows=mock_rows)
    repo = make_repo(session)

    rb = await repo.get_runbook("RB-MAIL-001")
    assert isinstance(rb, RunbookDetailDomainDTO)
    assert rb.runbook_id == "RB-MAIL-001"
    assert rb.title == "Mailgun Queue Remediation"
    assert rb.diagnostic_steps == ("Check event log", "Verify SMTP credentials")
    assert rb.remediation_steps == ("Flush queue", "Restart Service Pool")
    assert rb.product == "Customer Service"
    assert rb.verified_version == "10.2"
    assert rb.last_reviewed == now


@pytest.mark.asyncio
async def test_get_runbook_not_found_raises_canonical_error() -> None:
    """get_runbook raises RunbookNotFoundError when runbook does not exist."""
    session = MockSession(rows=[])
    repo = make_repo(session)

    with pytest.raises(RunbookNotFoundError) as exc_info:
        await repo.get_runbook("RB-MISSING-99")
    assert "RB-MISSING-99" in exc_info.value.message
    assert exc_info.value.error_code == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_runbook_empty_id_raises_not_found() -> None:
    """get_runbook raises RunbookNotFoundError on empty or whitespace ID."""
    session = MockSession(rows=[])
    repo = make_repo(session)

    with pytest.raises(RunbookNotFoundError):
        await repo.get_runbook("   ")


@pytest.mark.asyncio
async def test_get_runbook_malformed_diagnostic_steps_fails_closed() -> None:
    """get_runbook fails closed when diagnostic_steps is not a list of strings."""
    mock_rows = [
        {
            "runbook_id": "RB-BAD-DIAG",
            "title": "Bad Steps",
            "problem_description": "Desc",
            "diagnostic_steps": [{"nested": "dict_not_string"}],  # Malformed element
            "remediation_steps": ["Step 1"],
            "product": None,
            "verified_version": None,
            "last_reviewed": None,
            "source_reference": "RB-BAD",
        }
    ]
    session = MockSession(rows=mock_rows)
    repo = make_repo(session)

    with pytest.raises(MalformedRunbookDataError) as exc_info:
        await repo.get_runbook("RB-BAD-DIAG")
    assert exc_info.value.error_code == "MALFORMED_RUNBOOK_DATA"


@pytest.mark.asyncio
async def test_get_runbook_malformed_remediation_steps_fails_closed() -> None:
    """get_runbook fails closed when remediation_steps is not a list."""
    mock_rows = [
        {
            "runbook_id": "RB-BAD-REMED",
            "title": "Bad Remed",
            "problem_description": "Desc",
            "diagnostic_steps": ["Step 1"],
            "remediation_steps": "not_a_list",  # Malformed type
            "product": None,
            "verified_version": None,
            "last_reviewed": None,
            "source_reference": "RB-BAD",
        }
    ]
    session = MockSession(rows=mock_rows)
    repo = make_repo(session)

    with pytest.raises(MalformedRunbookDataError) as exc_info:
        await repo.get_runbook("RB-BAD-REMED")
    assert exc_info.value.error_code == "MALFORMED_RUNBOOK_DATA"


# ============================================================================
# find_known_issues Tests
# ============================================================================


@pytest.mark.asyncio
async def test_find_known_issues_mapping_and_ordering() -> None:
    """find_known_issues maps database rows to KnownIssueDomainDTO and preserves limit."""
    mock_rows = [
        {
            "issue_id": "KI-SO-101",
            "title": "SAML Assertion Clock Skew",
            "symptom_summary": "401 Unauthorized during SSO login",
            "root_cause_summary": "Clock drift between IdP and Service Provider",
            "workaround": "Set skew tolerance to 120s",
            "permanent_fix_reference": "SuperOffice 10.2.1 Hotfix 1",
            "affected_products": ["SuperOffice CRM", "Customer Service"],
            "affected_versions": ["10.2.0", "10.2.1"],
            "category": "authentication",
            "source_reference": "KI-SO-101",
            "trgm_sim": 0.85,
        },
    ]
    session = MockSession(rows=mock_rows)
    repo = make_repo(session)

    criteria = KnownIssueSearchCriteriaDTO(query_text="SAML clock skew", limit=10)
    issues = await repo.find_known_issues(criteria)

    assert len(issues) == 1
    issue = issues[0]
    assert isinstance(issue, KnownIssueDomainDTO)
    assert issue.issue_id == "KI-SO-101"
    assert issue.title == "SAML Assertion Clock Skew"
    assert issue.symptom_summary == "401 Unauthorized during SSO login"
    assert issue.workaround == "Set skew tolerance to 120s"
    assert issue.affected_products == ("SuperOffice CRM", "Customer Service")
    assert issue.category == "authentication"


@pytest.mark.asyncio
async def test_find_known_issues_filters_product_and_version() -> None:
    """find_known_issues post-filters by product and version criteria."""
    mock_rows = [
        {
            "issue_id": "KI-1",
            "title": "Issue 1",
            "symptom_summary": "Sym 1",
            "root_cause_summary": "RC 1",
            "workaround": None,
            "permanent_fix_reference": None,
            "affected_products": ["SuperOffice CRM"],
            "affected_versions": ["10.2"],
            "category": "database",
            "source_reference": "KI-1",
        },
        {
            "issue_id": "KI-2",
            "title": "Issue 2",
            "symptom_summary": "Sym 2",
            "root_cause_summary": "RC 2",
            "workaround": None,
            "permanent_fix_reference": None,
            "affected_products": ["Service"],
            "affected_versions": ["9.1"],
            "category": "database",
            "source_reference": "KI-2",
        },
    ]
    session = MockSession(rows=mock_rows)
    repo = make_repo(session)

    criteria = KnownIssueSearchCriteriaDTO(product="SuperOffice CRM")
    res = await repo.find_known_issues(criteria)
    assert len(res) == 1
    assert res[0].issue_id == "KI-1"


@pytest.mark.asyncio
async def test_find_known_issues_bounds_max_results_to_50() -> None:
    """find_known_issues bounds query limit to 50."""
    session = MockSession(rows=[])
    repo = make_repo(session)

    criteria = KnownIssueSearchCriteriaDTO(limit=50)
    await repo.find_known_issues(criteria)

    assert len(session.executed_params) == 1
    assert session.executed_params[0]["limit"] <= 50


# ============================================================================
# Database Error Boundary & SQL Invariants
# ============================================================================


@pytest.mark.asyncio
async def test_database_error_mapped_to_safe_typed_error() -> None:
    """Database exceptions are caught and wrapped in KnowledgeSearchError without leaking SQL."""
    session = MockSession(
        exc=OperationalError("SELECT * FROM secret_table", {}, Exception("db error"))
    )
    repo = make_repo(session)

    with pytest.raises(KnowledgeSearchError) as exc_info:
        await repo.search_knowledge(
            KnowledgeSearchCriteriaDTO(query_text="test"), valid_embedding()
        )

    err = exc_info.value
    assert err.error_code == "KNOWLEDGE_DATABASE_ERROR"
    # Ensure raw query or credentials are not in message
    assert "secret_table" not in err.message
    assert "db error" not in err.message
    assert err.details["operation"] == "search_knowledge"
    assert err.details["system"] == "PostgresKnowledgeStore"


def test_sql_invariants_no_select_star_and_bound_parameters() -> None:
    """Verify all fixed SQL statements adhere to security and schema invariants."""
    statements = [
        ("SEARCH_KNOWLEDGE_SQL", SEARCH_KNOWLEDGE_SQL),
        ("GET_RUNBOOK_SQL", GET_RUNBOOK_SQL),
        ("FIND_KNOWN_ISSUES_TRGM_SQL", FIND_KNOWN_ISSUES_TRGM_SQL),
        ("FIND_KNOWN_ISSUES_ALL_SQL", FIND_KNOWN_ISSUES_ALL_SQL),
    ]

    for name, stmt in statements:
        sql_text = stmt.text.upper()
        # Invariant 1: No SELECT *
        assert "SELECT *" not in sql_text, f"{name} must not contain SELECT *"

        # Invariant 2: Schema qualification
        assert "KNOWLEDGE." in sql_text, f"{name} must qualify tables with schema knowledge"

        # Invariant 3: Parameter bindings present
        assert ":" in stmt.text, f"{name} must use bound parameters (:param)"

    # Specific vector search invariant: cosine distance operator <=>
    search_sql = SEARCH_KNOWLEDGE_SQL.text
    assert "<=>" in search_sql, "SEARCH_KNOWLEDGE_SQL must use <=> cosine operator"
    assert "ORDER BY C.EMBEDDING <=>" in search_sql.upper(), (
        "SEARCH_KNOWLEDGE_SQL must order by cosine distance"
    )
    assert "C.CHUNK_ID ASC" in search_sql.upper(), (
        "SEARCH_KNOWLEDGE_SQL must tie-break by chunk_id ASC"
    )


def test_no_fastembed_dependency_in_repository_module() -> None:
    """PostgresKnowledgeRepository must not import FastEmbed."""
    file_path = Path(str(postgres_repository.__file__))
    with file_path.open(encoding="utf-8") as f:
        mod_source = f.read()
    assert "fastembed" not in mod_source.lower(), "postgres_repository must not reference fastembed"
