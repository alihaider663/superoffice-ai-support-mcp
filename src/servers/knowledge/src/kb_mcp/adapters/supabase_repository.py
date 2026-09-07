"""Supabase / pgvector Knowledge Repository implementation."""

import re
import urllib.parse
from datetime import UTC, datetime
from typing import Any

import httpx

from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnowledgeSearchResultDomainDTO,
    KnownIssueDomainDTO,
    KnownIssueSearchCriteriaDTO,
    RunbookDetailDomainDTO,
)
from kb_mcp.contracts.errors import (
    KnowledgeSearchError,
    RunbookNotFoundError,
)
from kb_mcp.contracts.interfaces import KnowledgeRepository
from kb_mcp.settings import KnowledgeServerSettings

# Regex to strip URLs, keys, and authorization headers from error strings
_RE_URL = re.compile(r"https?://[^\s/?#]+[^\s]*", re.IGNORECASE)
_RE_KEY = re.compile(r"(?:apikey|key|token|bearer)[=:\s]+[A-Za-z0-9_\-\.]{10,}", re.IGNORECASE)


class SupabaseKnowledgeRepository(KnowledgeRepository):
    """Knowledge Repository backed by Supabase REST / PostgREST endpoints.

    Enforces bounded result sets, secret/URL redaction on errors, and fail-closed handling.
    """

    def __init__(
        self,
        settings: KnowledgeServerSettings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client

    def _sanitize_error_message(self, raw_message: str) -> str:
        """Strip URLs, API keys, and connection credentials from error text."""
        sanitized = _RE_URL.sub("[ENDPOINT_REDACTED]", raw_message)
        sanitized = _RE_KEY.sub("[KEY_REDACTED]", sanitized)
        return sanitized

    def _handle_exception(self, exc: Exception, operation: str) -> None:
        """Translate HTTP, connection, and parser exceptions into KnowledgeSearchError."""
        if isinstance(exc, (RunbookNotFoundError, KnowledgeSearchError)):
            raise exc

        raw_str = str(exc)
        sanitized_msg = self._sanitize_error_message(raw_str)

        if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
            raise KnowledgeSearchError(
                message=f"Knowledge retrieval timed out during {operation}.",
                error_code="KNOWLEDGE_TIMEOUT",
                details={"operation": operation},
            ) from None

        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                raise KnowledgeSearchError(
                    message=f"Authentication failed with knowledge store during {operation}.",
                    error_code="KNOWLEDGE_AUTH_FAILURE",
                    details={"operation": operation},
                ) from None
            if status_code == 404:
                raise KnowledgeSearchError(
                    message=f"Knowledge endpoint or resource not found during {operation}.",
                    error_code="KNOWLEDGE_ENDPOINT_NOT_FOUND",
                    details={"operation": operation},
                ) from None

        raise KnowledgeSearchError(
            message=f"Knowledge retrieval failed during {operation}: {sanitized_msg}",
            error_code="KNOWLEDGE_SEARCH_ERROR",
            details={"operation": operation},
        ) from None

    def _map_document_row(self, row: dict[str, Any]) -> KnowledgeSearchResultDomainDTO:
        """Map raw PostgREST response row to KnowledgeSearchResultDomainDTO."""
        raw_score = row.get("similarity") or row.get("relevance_score") or row.get("score") or 0.0
        try:
            score = max(0.0, min(1.0, float(raw_score)))
        except (ValueError, TypeError):
            score = 0.0

        tags_raw = row.get("tags") or ()
        if isinstance(tags_raw, (list, tuple)):
            tags = tuple(str(t) for t in tags_raw if t)
        elif isinstance(tags_raw, str):
            tags = tuple(t.strip() for t in tags_raw.split(",") if t.strip())
        else:
            tags = ()

        return KnowledgeSearchResultDomainDTO(
            document_id=str(row.get("document_id") or row.get("id") or "DOC-UNKNOWN"),
            title=str(row.get("title") or "Untitled Document"),
            content_excerpt=str(row.get("content_excerpt") or row.get("content") or ""),
            category=str(row.get("category") or "general"),
            product=str(row.get("product")) if row.get("product") else None,
            version=str(row.get("version")) if row.get("version") else None,
            tags=tags,
            relevance_score=score,
            source_reference=str(
                row.get("source_reference")
                or row.get("document_id")
                or row.get("id")
                or "REF-UNKNOWN"
            ),
        )

    def _map_runbook_row(self, row: dict[str, Any]) -> RunbookDetailDomainDTO:
        """Map raw PostgREST response row to RunbookDetailDomainDTO."""
        diag_raw = row.get("diagnostic_steps") or ()
        if isinstance(diag_raw, (list, tuple)):
            diag_steps = tuple(str(s) for s in diag_raw if s)
        elif isinstance(diag_raw, str):
            diag_steps = tuple(s.strip() for s in diag_raw.split("\n") if s.strip())
        else:
            diag_steps = ()

        remed_raw = row.get("remediation_steps") or ()
        if isinstance(remed_raw, (list, tuple)):
            remed_steps = tuple(str(s) for s in remed_raw if s)
        elif isinstance(remed_raw, str):
            remed_steps = tuple(s.strip() for s in remed_raw.split("\n") if s.strip())
        else:
            remed_steps = ()

        last_rev = row.get("last_reviewed")
        if isinstance(last_rev, str):
            try:
                last_reviewed = datetime.fromisoformat(last_rev)
                if not last_reviewed.tzinfo:
                    last_reviewed = last_reviewed.replace(tzinfo=UTC)
            except ValueError:
                last_reviewed = None
        elif isinstance(last_rev, datetime):
            last_reviewed = last_rev if last_rev.tzinfo else last_rev.replace(tzinfo=UTC)
        else:
            last_reviewed = None

        prod = str(row.get("product")) if row.get("product") else None
        ver = str(row.get("verified_version")) if row.get("verified_version") else None

        return RunbookDetailDomainDTO(
            runbook_id=str(row.get("runbook_id") or row.get("id") or "RB-UNKNOWN"),
            title=str(row.get("title") or "Untitled Runbook"),
            problem_description=str(row.get("problem_description") or row.get("description") or ""),
            diagnostic_steps=diag_steps,
            remediation_steps=remed_steps,
            product=prod,
            verified_version=ver,
            last_reviewed=last_reviewed,
            source_reference=str(
                row.get("source_reference")
                or row.get("runbook_id")
                or row.get("id")
                or "REF-UNKNOWN"
            ),
        )

    def _map_known_issue_row(self, row: dict[str, Any]) -> KnownIssueDomainDTO:
        """Map raw PostgREST response row to KnownIssueDomainDTO."""
        aff_prods = row.get("affected_products") or ()
        if isinstance(aff_prods, (list, tuple)):
            products = tuple(str(p) for p in aff_prods if p)
        elif isinstance(aff_prods, str):
            products = tuple(p.strip() for p in aff_prods.split(",") if p.strip())
        else:
            products = ()

        aff_vers = row.get("affected_versions") or ()
        if isinstance(aff_vers, (list, tuple)):
            versions = tuple(str(v) for v in aff_vers if v)
        elif isinstance(aff_vers, str):
            versions = tuple(v.strip() for v in aff_vers.split(",") if v.strip())
        else:
            versions = ()

        return KnownIssueDomainDTO(
            issue_id=str(row.get("issue_id") or row.get("id") or "KI-UNKNOWN"),
            title=str(row.get("title") or "Untitled Known Issue"),
            symptom_summary=str(row.get("symptom_summary") or row.get("symptom") or ""),
            root_cause_summary=str(row.get("root_cause_summary") or row.get("root_cause") or ""),
            workaround=str(row.get("workaround")) if row.get("workaround") else None,
            permanent_fix_reference=(
                str(row.get("permanent_fix_reference"))
                if row.get("permanent_fix_reference")
                else None
            ),
            affected_products=products,
            affected_versions=versions,
            category=str(row.get("category") or "general"),
            source_reference=str(
                row.get("source_reference") or row.get("issue_id") or row.get("id") or "REF-UNKNOWN"
            ),
        )

    def _build_auth_headers(self) -> dict[str, str]:
        """Build standard Supabase REST authorization headers."""
        key_val = self._settings.supabase_anon_key.get_secret_value()
        return {
            "apikey": key_val,
            "Authorization": f"Bearer {key_val}",
        }

    async def search_knowledge(
        self, criteria: KnowledgeSearchCriteriaDTO
    ) -> tuple[KnowledgeSearchResultDomainDTO, ...]:
        """Perform semantic search across knowledge documentation."""
        if not self._http_client:
            raise KnowledgeSearchError(
                message="Supabase knowledge client is not configured or initialized.",
                error_code="KNOWLEDGE_CLIENT_NOT_CONFIGURED",
                details={"operation": "search_knowledge"},
            )

        if not self._settings.match_documents_rpc:
            raise KnowledgeSearchError(
                message="Vector search RPC mapping is not configured.",
                error_code="KNOWLEDGE_BACKEND_NOT_CONFIGURED",
                details={"operation": "search_knowledge"},
            )

        effective_limit = min(criteria.limit, 50)
        base_url = str(self._settings.supabase_url).rstrip("/")
        endpoint = f"{base_url}/rest/v1/rpc/{self._settings.match_documents_rpc}"

        payload: dict[str, Any] = {
            "query_text": criteria.query_text,
            "match_count": effective_limit,
        }
        if criteria.category:
            payload["filter_category"] = criteria.category
        if criteria.product:
            payload["filter_product"] = criteria.product
        if criteria.version:
            payload["filter_version"] = criteria.version
        if criteria.min_relevance_score is not None:
            payload["match_threshold"] = criteria.min_relevance_score

        headers = self._build_auth_headers()
        headers["Content-Type"] = "application/json"

        try:
            response = await self._http_client.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=float(self._settings.timeout_seconds),
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            self._handle_exception(exc, "search_knowledge")

        if not isinstance(data, list):
            return ()

        results: list[KnowledgeSearchResultDomainDTO] = []
        for row in data:
            if isinstance(row, dict):
                doc = self._map_document_row(row)
                if (
                    criteria.min_relevance_score is None
                    or doc.relevance_score >= criteria.min_relevance_score
                ):
                    results.append(doc)

        return tuple(results[:effective_limit])

    async def get_runbook(self, runbook_id: str) -> RunbookDetailDomainDTO:
        """Fetch a specific operational runbook or guide by its identifier."""
        if not self._http_client:
            raise KnowledgeSearchError(
                message="Supabase knowledge client is not configured or initialized.",
                error_code="KNOWLEDGE_CLIENT_NOT_CONFIGURED",
                details={"operation": "get_runbook", "runbook_id": runbook_id},
            )

        if not self._settings.runbooks_table:
            raise KnowledgeSearchError(
                message="Runbooks table/view mapping is not configured.",
                error_code="KNOWLEDGE_BACKEND_NOT_CONFIGURED",
                details={"operation": "get_runbook", "runbook_id": runbook_id},
            )

        base_url = str(self._settings.supabase_url).rstrip("/")
        quoted_id = urllib.parse.quote(runbook_id)
        table_name = self._settings.runbooks_table
        endpoint = f"{base_url}/rest/v1/{table_name}?runbook_id=eq.{quoted_id}&select=*"

        try:
            response = await self._http_client.get(
                endpoint,
                headers=self._build_auth_headers(),
                timeout=float(self._settings.timeout_seconds),
            )
            if response.status_code == 404:
                raise RunbookNotFoundError(runbook_id)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            self._handle_exception(exc, "get_runbook")

        if not isinstance(data, list) or len(data) == 0:
            raise RunbookNotFoundError(runbook_id)

        first_row = data[0]
        if not isinstance(first_row, dict):
            raise RunbookNotFoundError(runbook_id)

        return self._map_runbook_row(first_row)

    async def find_known_issues(
        self, criteria: KnownIssueSearchCriteriaDTO
    ) -> tuple[KnownIssueDomainDTO, ...]:
        """Query verified known issues matching symptom keywords and product context."""
        if not self._http_client:
            raise KnowledgeSearchError(
                message="Supabase knowledge client is not configured or initialized.",
                error_code="KNOWLEDGE_CLIENT_NOT_CONFIGURED",
                details={"operation": "find_known_issues"},
            )

        if not self._settings.known_issues_table:
            raise KnowledgeSearchError(
                message="Known issues table/view mapping is not configured.",
                error_code="KNOWLEDGE_BACKEND_NOT_CONFIGURED",
                details={"operation": "find_known_issues"},
            )

        effective_limit = min(criteria.limit, 50)
        base_url = str(self._settings.supabase_url).rstrip("/")
        params: list[str] = [f"limit={effective_limit}", "select=*"]

        if criteria.category:
            params.append(f"category=eq.{urllib.parse.quote(criteria.category)}")
        if criteria.query_text:
            params.append(f"title=ilike.*{urllib.parse.quote(criteria.query_text)}*")

        query_str = "&".join(params)
        endpoint = f"{base_url}/rest/v1/{self._settings.known_issues_table}?{query_str}"

        try:
            response = await self._http_client.get(
                endpoint,
                headers=self._build_auth_headers(),
                timeout=float(self._settings.timeout_seconds),
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            self._handle_exception(exc, "find_known_issues")

        if not isinstance(data, list):
            return ()

        issues: list[KnownIssueDomainDTO] = []
        for row in data:
            if isinstance(row, dict):
                issue = self._map_known_issue_row(row)
                issues.append(issue)

        return tuple(issues[:effective_limit])
