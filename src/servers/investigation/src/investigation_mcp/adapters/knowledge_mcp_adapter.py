"""Knowledge Base MCP client adapter satisfying Layer-4 KnowledgeServicePort."""

import json
from collections.abc import Sequence
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnowledgeSearchResultDomainDTO,
    KnownIssueDomainDTO,
    KnownIssueSearchCriteriaDTO,
    RunbookDetailDomainDTO,
)
from kb_mcp.contracts.errors import KnowledgeBackendNotConfiguredError, KnowledgeSearchError
from platform_investigation_service.ports import KnowledgeServicePort
from platform_observability.logging import get_logger

logger = get_logger(__name__)

TOOL_NAME_SEARCH_KNOWLEDGE = "search_knowledge"
TOOL_NAME_FIND_KNOWN_ISSUES = "find_known_issues"
TOOL_NAME_GET_RUNBOOK = "get_runbook"


class KnowledgeMcpClientAdapter(KnowledgeServicePort):
    """Downstream MCP client adapter for Knowledge Base and Runbooks.

    Implements KnowledgeServicePort using official MCP streamable_http_client.
    Invokes strictly the three knowledge capabilities:
    - search_knowledge
    - find_known_issues
    - get_runbook
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8003",
        endpoint_path: str = "/mcp",
        http_client: httpx.AsyncClient | None = None,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._endpoint_path = endpoint_path
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds

    def _build_headers(self) -> dict[str, str]:
        return {}

    def _extract_payload(self, tool_result: CallToolResult) -> Any:
        if tool_result.structuredContent is not None:
            return tool_result.structuredContent

        texts: list[str] = [
            item.text for item in tool_result.content if isinstance(item, TextContent)
        ]
        joined_text = "\n".join(texts).strip()
        if not joined_text:
            return {}

        try:
            return json.loads(joined_text)
        except json.JSONDecodeError:
            return {"raw_text": joined_text}

    def _extract_error_message(self, tool_result: CallToolResult, tool_name: str) -> str:
        for item in tool_result.content:
            if isinstance(item, TextContent) and item.text.strip():
                return item.text.strip()
        return f"Knowledge MCP tool '{tool_name}' returned an error."

    async def _execute_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        endpoint_url = f"{self._base_url}{self._endpoint_path}"
        headers = self._build_headers()
        timeout = httpx.Timeout(self._timeout_seconds)

        client_to_use = self._http_client
        owns_client = False

        if client_to_use is None:
            client_to_use = httpx.AsyncClient(
                headers=headers,
                timeout=timeout,
                follow_redirects=False,
            )
            owns_client = True
        else:
            client_to_use.headers.update(headers)

        try:
            async with (
                streamable_http_client(
                    endpoint_url,
                    http_client=client_to_use,
                ) as (read_stream, write_stream, _),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                tool_result: CallToolResult = await session.call_tool(
                    name=tool_name,
                    arguments=arguments,
                )

                if tool_result.isError:
                    error_msg = self._extract_error_message(tool_result, tool_name)
                    if "not configured" in error_msg.lower():
                        raise KnowledgeBackendNotConfiguredError(error_msg)
                    raise KnowledgeSearchError(
                        f"Downstream {tool_name} failed: {error_msg}",
                        error_code="DOWNSTREAM_KNOWLEDGE_ERROR",
                    )

                return self._extract_payload(tool_result)

        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning(
                "Knowledge MCP tool call timed out",
                tool=tool_name,
                endpoint=endpoint_url,
                error=str(exc),
            )
            raise KnowledgeSearchError(
                f"Knowledge MCP server timed out during {tool_name}.",
                error_code="DOWNSTREAM_TIMEOUT",
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Knowledge MCP server returned HTTP error status",
                status_code=exc.response.status_code,
                endpoint=endpoint_url,
            )
            raise KnowledgeSearchError(
                f"Knowledge MCP server returned HTTP status {exc.response.status_code}.",
                error_code="DOWNSTREAM_UNAVAILABLE",
            ) from exc
        except (KnowledgeSearchError, KnowledgeBackendNotConfiguredError):
            raise
        except Exception as exc:
            logger.error(
                "Knowledge MCP communication failed",
                tool=tool_name,
                endpoint=endpoint_url,
                error=str(exc),
            )
            raise KnowledgeSearchError(
                f"Failed to communicate with Knowledge MCP server: {exc}",
                error_code="DOWNSTREAM_UNAVAILABLE",
            ) from exc
        finally:
            if owns_client:
                await client_to_use.aclose()

    async def search_knowledge(
        self,
        criteria: KnowledgeSearchCriteriaDTO,
    ) -> Sequence[KnowledgeSearchResultDomainDTO]:
        args: dict[str, Any] = {
            "query_text": criteria.query_text,
            "max_results": criteria.limit,
        }
        raw_payload = await self._execute_tool_call(TOOL_NAME_SEARCH_KNOWLEDGE, args)
        if isinstance(raw_payload, list):
            return [KnowledgeSearchResultDomainDTO.model_validate(item) for item in raw_payload]
        return []

    async def find_known_issues(
        self,
        criteria: KnownIssueSearchCriteriaDTO,
    ) -> Sequence[KnownIssueDomainDTO]:
        args: dict[str, Any] = {
            "query_text": criteria.query_text or "",
            "max_results": criteria.limit,
        }
        raw_payload = await self._execute_tool_call(TOOL_NAME_FIND_KNOWN_ISSUES, args)
        if isinstance(raw_payload, list):
            return [KnownIssueDomainDTO.model_validate(item) for item in raw_payload]
        return []

    async def get_runbook(
        self,
        runbook_id: str,
    ) -> RunbookDetailDomainDTO | None:
        args: dict[str, Any] = {"runbook_id": runbook_id}
        try:
            raw_payload = await self._execute_tool_call(TOOL_NAME_GET_RUNBOOK, args)
            if isinstance(raw_payload, dict) and raw_payload:
                return RunbookDetailDomainDTO.model_validate(raw_payload)
            return None
        except Exception:
            return None
