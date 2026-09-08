"""PostgreSQL and pgvector Knowledge Repository implementation using SQLAlchemy 2 Async."""

import logging
import math
from collections.abc import Sequence
from datetime import datetime
from typing import Any, NoReturn

from pgvector.sqlalchemy import Vector
from sqlalchemy import Integer, String, bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnowledgeSearchResultDomainDTO,
    KnownIssueDomainDTO,
    KnownIssueSearchCriteriaDTO,
    RunbookDetailDomainDTO,
)
from kb_mcp.contracts.errors import (
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingInputError,
    KnowledgeSearchError,
    MalformedRunbookDataError,
    RunbookNotFoundError,
)
from kb_mcp.contracts.interfaces import KnowledgeRepository

logger = logging.getLogger(__name__)

SEARCH_KNOWLEDGE_SQL = text(
    """
    SELECT
        c.chunk_id,
        c.document_id,
        d.title,
        c.content,
        d.document_type,
        d.version,
        d.source_reference,
        (c.embedding <=> :query_vector) AS cosine_distance
    FROM knowledge.chunks AS c
    JOIN knowledge.documents AS d ON c.document_id = d.document_id
    WHERE (CAST(:category AS VARCHAR) IS NULL OR d.document_type = :category)
    ORDER BY c.embedding <=> :query_vector ASC, c.chunk_id ASC
    LIMIT :limit
    """
).bindparams(
    bindparam("query_vector", type_=Vector(384)),
    bindparam("category", type_=String()),
    bindparam("limit", type_=Integer()),
)

GET_RUNBOOK_SQL = text(
    """
    SELECT
        runbook_id,
        title,
        problem_description,
        diagnostic_steps,
        remediation_steps,
        product,
        verified_version,
        last_reviewed,
        source_reference
    FROM knowledge.runbooks
    WHERE runbook_id = :runbook_id
    LIMIT 1
    """
).bindparams(
    bindparam("runbook_id", type_=String()),
)

FIND_KNOWN_ISSUES_TRGM_SQL = text(
    """
    SELECT
        issue_id,
        title,
        symptom_summary,
        root_cause_summary,
        workaround,
        permanent_fix_reference,
        affected_products,
        affected_versions,
        category,
        source_reference,
        similarity(title, :query_text) AS trgm_sim
    FROM knowledge.known_issues
    WHERE (CAST(:category AS VARCHAR) IS NULL OR category = :category)
      AND (title % :query_text OR title ILIKE :like_pattern)
    ORDER BY trgm_sim DESC, issue_id ASC
    LIMIT :limit
    """
).bindparams(
    bindparam("query_text", type_=String()),
    bindparam("like_pattern", type_=String()),
    bindparam("category", type_=String()),
    bindparam("limit", type_=Integer()),
)

FIND_KNOWN_ISSUES_ALL_SQL = text(
    """
    SELECT
        issue_id,
        title,
        symptom_summary,
        root_cause_summary,
        workaround,
        permanent_fix_reference,
        affected_products,
        affected_versions,
        category,
        source_reference
    FROM knowledge.known_issues
    WHERE (CAST(:category AS VARCHAR) IS NULL OR category = :category)
    ORDER BY issue_id ASC
    LIMIT :limit
    """
).bindparams(
    bindparam("category", type_=String()),
    bindparam("limit", type_=Integer()),
)


class PostgresKnowledgeRepository(KnowledgeRepository):
    """Read-only Knowledge repository backed by PostgreSQL 16, pgvector, and pg_trgm."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | AsyncEngine,
        *,
        timeout_seconds: float = 10.0,
        max_results_ceiling: int = 50,
    ) -> None:
        if isinstance(session_factory, AsyncEngine):
            self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
                bind=session_factory, expire_on_commit=False
            )
        else:
            self._sessionmaker = session_factory

        self._timeout_seconds = timeout_seconds
        self._max_results_ceiling = min(max(1, max_results_ceiling), 50)

    def _handle_db_exception(self, exc: Exception, operation: str) -> NoReturn:
        """Map database exception into safe KnowledgeSearchError without leaking internals."""
        logger.error(
            "Knowledge database operation failed",
            extra={"operation": operation, "error_type": type(exc).__name__},
        )
        raise KnowledgeSearchError(
            "A database error occurred while querying the knowledge repository.",
            system_name="PostgresKnowledgeStore",
            error_code="KNOWLEDGE_DATABASE_ERROR",
            details={"operation": operation},
        ) from None

    def _validate_runbook_steps(self, steps_data: Any, field_name: str) -> tuple[str, ...]:
        """Validate that JSONB step data is an ordered collection of strings."""
        if not isinstance(steps_data, (list, tuple)):
            raise MalformedRunbookDataError(
                f"Runbook field '{field_name}' must be an ordered list of strings.",
                details={"field": field_name},
            )
        validated: list[str] = []
        for step in steps_data:
            if not isinstance(step, str):
                raise MalformedRunbookDataError(
                    f"Runbook field '{field_name}' contains non-string elements.",
                    details={"field": field_name},
                )
            validated.append(step)
        return tuple(validated)

    def _extract_string_tuple(self, val: Any) -> tuple[str, ...]:
        """Safely extract string tuple from JSONB list or comma-separated string."""
        if isinstance(val, (list, tuple)):
            return tuple(str(x) for x in val if x)
        if isinstance(val, str):
            return tuple(p.strip() for p in val.split(",") if p.strip())
        return ()

    async def search_knowledge(
        self,
        criteria: KnowledgeSearchCriteriaDTO,
        query_embedding: Sequence[float],
    ) -> tuple[KnowledgeSearchResultDomainDTO, ...]:
        """Perform semantic vector retrieval against knowledge.chunks and knowledge.documents."""
        if not isinstance(query_embedding, Sequence):
            raise EmbeddingInputError("Query embedding must be a non-empty sequence of floats.")

        if len(query_embedding) != 384:
            raise EmbeddingDimensionError(
                actual_dimension=len(query_embedding),
                expected_dimension=384,
            )

        for val in query_embedding:
            if not isinstance(val, (int, float)) or not math.isfinite(val):
                raise EmbeddingInputError("Query embedding values must be finite numbers.")

        effective_limit = min(max(1, criteria.limit), self._max_results_ceiling)

        try:
            async with self._sessionmaker() as session:
                result = await session.execute(
                    SEARCH_KNOWLEDGE_SQL,
                    {
                        "query_vector": list(query_embedding),
                        "category": criteria.category,
                        "limit": effective_limit,
                    },
                )
                rows = result.mappings().fetchall()
        except (EmbeddingError, RunbookNotFoundError, MalformedRunbookDataError):
            raise
        except Exception as exc:
            self._handle_db_exception(exc, "search_knowledge")

        results: list[KnowledgeSearchResultDomainDTO] = []
        for row in rows:
            dist = float(row["cosine_distance"])
            if not math.isfinite(dist):
                dist = 1.0
            relevance = round(max(0.0, min(1.0, 1.0 - dist)), 4)

            if (
                criteria.min_relevance_score is not None
                and relevance < criteria.min_relevance_score
            ):
                continue

            results.append(
                KnowledgeSearchResultDomainDTO(
                    document_id=str(row["document_id"]),
                    title=str(row["title"]),
                    content_excerpt=str(row["content"]),
                    category=str(row["document_type"]),
                    product=None,
                    version=str(row["version"]) if row["version"] is not None else None,
                    tags=(),
                    relevance_score=relevance,
                    source_reference=str(row["source_reference"]),
                )
            )

        logger.info(
            "Knowledge semantic search complete",
            extra={"operation": "search_knowledge", "count": len(results)},
        )
        return tuple(results)

    async def get_runbook(self, runbook_id: str) -> RunbookDetailDomainDTO:
        """Fetch a specific operational runbook by its identifier."""
        if not runbook_id or not runbook_id.strip():
            raise RunbookNotFoundError(runbook_id or "<empty>")

        try:
            async with self._sessionmaker() as session:
                result = await session.execute(
                    GET_RUNBOOK_SQL,
                    {"runbook_id": runbook_id.strip()},
                )
                row = result.mappings().first()
        except (RunbookNotFoundError, MalformedRunbookDataError):
            raise
        except Exception as exc:
            self._handle_db_exception(exc, "get_runbook")

        if row is None:
            raise RunbookNotFoundError(runbook_id)

        diag_steps = self._validate_runbook_steps(row["diagnostic_steps"], "diagnostic_steps")
        remed_steps = self._validate_runbook_steps(row["remediation_steps"], "remediation_steps")

        last_rev = row["last_reviewed"]
        if last_rev is not None and not isinstance(last_rev, datetime):
            last_rev = None

        logger.info(
            "Runbook retrieved successfully",
            extra={"operation": "get_runbook", "runbook_id": runbook_id},
        )
        return RunbookDetailDomainDTO(
            runbook_id=str(row["runbook_id"]),
            title=str(row["title"]),
            problem_description=str(row["problem_description"]),
            diagnostic_steps=diag_steps,
            remediation_steps=remed_steps,
            product=str(row["product"]) if row["product"] is not None else None,
            verified_version=(
                str(row["verified_version"]) if row["verified_version"] is not None else None
            ),
            last_reviewed=last_rev,
            source_reference=str(row["source_reference"]),
        )

    async def find_known_issues(
        self, criteria: KnownIssueSearchCriteriaDTO
    ) -> tuple[KnownIssueDomainDTO, ...]:
        """Query verified known issues matching symptom keywords and product context."""
        effective_limit = min(max(1, criteria.limit), self._max_results_ceiling)

        has_query_text = bool(criteria.query_text and criteria.query_text.strip())

        try:
            async with self._sessionmaker() as session:
                if has_query_text:
                    query_text = criteria.query_text.strip()  # type: ignore[union-attr]
                    like_pattern = f"%{query_text}%"
                    result = await session.execute(
                        FIND_KNOWN_ISSUES_TRGM_SQL,
                        {
                            "query_text": query_text,
                            "like_pattern": like_pattern,
                            "category": criteria.category,
                            "limit": effective_limit,
                        },
                    )
                else:
                    result = await session.execute(
                        FIND_KNOWN_ISSUES_ALL_SQL,
                        {
                            "category": criteria.category,
                            "limit": effective_limit,
                        },
                    )
                rows = result.mappings().fetchall()
        except Exception as exc:
            self._handle_db_exception(exc, "find_known_issues")

        issues: list[KnownIssueDomainDTO] = []
        for row in rows:
            prods = self._extract_string_tuple(row["affected_products"])
            vers = self._extract_string_tuple(row["affected_versions"])

            if criteria.product:
                prod_filter = criteria.product.lower()
                if not any(prod_filter in p.lower() for p in prods):
                    continue

            if criteria.version:
                ver_filter = criteria.version.lower()
                if not any(ver_filter in v.lower() for v in vers):
                    continue

            issues.append(
                KnownIssueDomainDTO(
                    issue_id=str(row["issue_id"]),
                    title=str(row["title"]),
                    symptom_summary=str(row["symptom_summary"]),
                    root_cause_summary=str(row["root_cause_summary"]),
                    workaround=str(row["workaround"]) if row["workaround"] else None,
                    permanent_fix_reference=(
                        str(row["permanent_fix_reference"])
                        if row["permanent_fix_reference"]
                        else None
                    ),
                    affected_products=prods,
                    affected_versions=vers,
                    category=str(row["category"]),
                    source_reference=str(row["source_reference"]),
                )
            )

        logger.info(
            "Known issues lookup complete",
            extra={"operation": "find_known_issues", "count": len(issues)},
        )
        return tuple(issues[:effective_limit])
