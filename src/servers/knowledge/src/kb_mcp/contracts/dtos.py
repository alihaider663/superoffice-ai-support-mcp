"""Data transfer objects for Knowledge retrieval, Runbooks, and Known Issues."""

from datetime import datetime

from pydantic import Field

from platform_core.models import PlatformBaseModel

# ============================================================================
# 1. Semantic & Structured Search Criteria DTOs
# ============================================================================


class KnowledgeSearchCriteriaDTO(PlatformBaseModel):
    """Structured criteria for semantic retrieval from the Knowledge repository."""

    query_text: str = Field(
        ...,
        min_length=2,
        max_length=512,
        description="Semantic search phrase (plain text data only; no query syntax)",
    )
    category: str | None = Field(
        default=None,
        description="Optional document category (e.g. troubleshooting, architecture, config)",
    )
    product: str | None = Field(
        default=None,
        description="Optional target product (e.g. SuperOffice CRM, Service, Admin)",
    )
    version: str | None = Field(
        default=None,
        description="Optional product version constraint (e.g. 10.2)",
    )
    tags: tuple[str, ...] = Field(
        default=(),
        description="Allowlisted keyword tags for filtering",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Top-K maximum results to return (default 5, max 50)",
    )
    min_relevance_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional minimum normalized similarity threshold (0.0 to 1.0)",
    )


class KnownIssueSearchCriteriaDTO(PlatformBaseModel):
    """Structured criteria for searching verified known issues and workarounds."""

    query_text: str | None = Field(
        default=None,
        max_length=256,
        description="Symptom keywords or error code to match against known issues",
    )
    product: str | None = Field(
        default=None,
        description="Target affected product filter",
    )
    version: str | None = Field(
        default=None,
        description="Target affected product version filter",
    )
    category: str | None = Field(
        default=None,
        description="Issue category filter (e.g. database, auth, sync, mail)",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum matching known issues to return",
    )


# ============================================================================
# 2. Internal Domain DTOs (Restricted / Knowledge Adapter Layer)
# ============================================================================


class KnowledgeSearchResultDomainDTO(PlatformBaseModel):
    """Internal domain representation of a retrieved knowledge document or section chunk."""

    document_id: str = Field(..., description="Unique stable document identifier")
    title: str = Field(..., description="Document or section title")
    content_excerpt: str = Field(..., description="Extracted content text chunk")
    category: str = Field(..., description="Document classification category")
    product: str | None = Field(default=None, description="Associated product")
    version: str | None = Field(default=None, description="Verified product version")
    tags: tuple[str, ...] = Field(default=(), description="Associated keyword tags")
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Normalized similarity score (0.0 to 1.0)",
    )
    source_reference: str = Field(
        ...,
        description="Safe document reference code (e.g. DOC-ARCH-002, RB-AUTH-001)",
    )


class RunbookDetailDomainDTO(PlatformBaseModel):
    """Internal domain representation of an operational runbook or troubleshooting guide."""

    runbook_id: str = Field(..., description="Unique runbook identifier (e.g. RB-AUTH-001)")
    title: str = Field(..., description="Runbook title")
    problem_description: str = Field(..., description="Symptom and problem statement")
    diagnostic_steps: tuple[str, ...] = Field(
        default=(),
        description="Ordered diagnostic investigation steps",
    )
    remediation_steps: tuple[str, ...] = Field(
        default=(),
        description="Ordered resolution and recovery steps",
    )
    product: str | None = Field(default=None, description="Associated product name")
    verified_version: str | None = Field(
        default=None,
        description="Product version verified against",
    )
    last_reviewed: datetime | None = Field(
        default=None,
        description="Review or verification timestamp",
    )
    source_reference: str = Field(
        ...,
        description="Safe documentation reference identifier",
    )


class KnownIssueDomainDTO(PlatformBaseModel):
    """Internal domain representation of a verified known issue."""

    issue_id: str = Field(..., description="Unique known issue identifier (e.g. KI-SO-8821)")
    title: str = Field(..., description="Known issue summary title")
    symptom_summary: str = Field(
        ...,
        description="Observable symptoms and error manifestations",
    )
    root_cause_summary: str = Field(..., description="Root cause explanation")
    workaround: str | None = Field(
        default=None,
        description="Temporary mitigation or workaround instructions",
    )
    permanent_fix_reference: str | None = Field(
        default=None,
        description="Fix version or hotfix identifier",
    )
    affected_products: tuple[str, ...] = Field(
        default=(),
        description="List of affected products",
    )
    affected_versions: tuple[str, ...] = Field(
        default=(),
        description="List of affected version ranges",
    )
    category: str = Field(..., description="Issue classification category")
    source_reference: str = Field(..., description="Safe knowledge reference")


# ============================================================================
# 3. AI-Facing Minimized DTOs (Downstream Output Layer)
# ============================================================================


class MinimizedKnowledgeChunkDTO(PlatformBaseModel):
    """AI-Facing sanitized knowledge chunk safe for LLM context injection."""

    document_id: str = Field(..., description="Stable document reference")
    title: str = Field(..., description="Document title")
    content_excerpt: str = Field(..., description="Sanitized content text chunk")
    category: str = Field(..., description="Category label")
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Normalized similarity score",
    )
    source_reference: str = Field(..., description="Safe source identifier")


class MinimizedRunbookDTO(PlatformBaseModel):
    """AI-Facing sanitized runbook summary."""

    runbook_id: str = Field(..., description="Runbook reference")
    title: str = Field(..., description="Runbook title")
    problem_description: str = Field(..., description="Problem description")
    diagnostic_steps: tuple[str, ...] = Field(
        default=(),
        description="Investigation steps",
    )
    remediation_steps: tuple[str, ...] = Field(
        default=(),
        description="Resolution steps",
    )
    source_reference: str = Field(..., description="Safe source reference")


class MinimizedKnownIssueDTO(PlatformBaseModel):
    """AI-Facing sanitized known issue summary."""

    issue_id: str = Field(..., description="Issue reference identifier")
    title: str = Field(..., description="Issue summary title")
    symptom_summary: str = Field(..., description="Symptom description")
    workaround: str | None = Field(
        default=None,
        description="Workaround instructions",
    )
    source_reference: str = Field(..., description="Safe source reference")
