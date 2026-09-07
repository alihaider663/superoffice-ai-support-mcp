"""SuperOffice MCP client adapter satisfying Layer-4 SuperOfficeServicePort."""

import json
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

from platform_observability.logging import get_logger
from so_mcp.contracts.dtos import MinimizedTicketDetailDTO
from so_mcp.contracts.errors import SuperOfficeIntegrationError

logger = get_logger(__name__)

# Fixed internal tool name for SuperOffice ticket retrieval
TOOL_NAME_GET_TICKET = "get_ticket"


class SuperOfficeMcpClientAdapter:
    """Downstream MCP client adapter for SuperOffice CRM operations.

    Implements SuperOfficeServicePort using official MCP streamable_http_client.
    Passes only minimum necessary headers (X-Correlation-ID) and invokes strictly
    the frozen get_ticket capability.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8001",
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
        """Construct minimal second-hop transport headers.

        Under Phase 4.1 header minimization, backend MCP servers (so-mcp, diag-mcp)
        contain no inbound correlation or identity consumers. Therefore, the
        delegated/custom second-hop header set is strictly EMPTY.
        """
        return {}

    def _extract_payload(self, tool_result: CallToolResult) -> Any:
        """Extract structured or text JSON payload from CallToolResult."""
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

    def _extract_error_message(self, tool_result: CallToolResult) -> str:
        """Extract human-readable error text from failed CallToolResult."""
        for item in tool_result.content:
            if isinstance(item, TextContent) and item.text.strip():
                return item.text.strip()
        return "SuperOffice MCP get_ticket returned an error."

    async def get_ticket(
        self,
        ticket_id: int,
    ) -> MinimizedTicketDetailDTO:
        """Retrieve sanitized ticket detail via downstream SuperOffice MCP server.

        Invokes strictly the 'get_ticket' tool.
        """
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
                    name=TOOL_NAME_GET_TICKET,
                    arguments={"ticket_id": ticket_id},
                )

                if tool_result.isError:
                    error_msg = self._extract_error_message(tool_result)
                    raise SuperOfficeIntegrationError(
                        f"Downstream get_ticket failed: {error_msg}",
                        error_code="DOWNSTREAM_SUPEROFFICE_ERROR",
                    )

                raw_payload = self._extract_payload(tool_result)
                return MinimizedTicketDetailDTO.model_validate(raw_payload)

        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning(
                "SuperOffice MCP get_ticket timed out", endpoint=endpoint_url, error=str(exc)
            )
            raise SuperOfficeIntegrationError(
                "SuperOffice MCP server timed out during get_ticket.",
                error_code="DOWNSTREAM_TIMEOUT",
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "SuperOffice MCP server returned HTTP error status",
                status_code=exc.response.status_code,
                endpoint=endpoint_url,
            )
            raise SuperOfficeIntegrationError(
                f"SuperOffice MCP server returned HTTP status {exc.response.status_code}.",
                error_code="DOWNSTREAM_UNAVAILABLE",
            ) from exc
        except SuperOfficeIntegrationError:
            raise
        except Exception as exc:
            if "ValidationError" in type(exc).__name__:
                raise
            logger.error(
                "SuperOffice MCP get_ticket communication failed",
                endpoint=endpoint_url,
                error=str(exc),
            )
            raise SuperOfficeIntegrationError(
                f"Failed to communicate with SuperOffice MCP server: {exc}",
                error_code="DOWNSTREAM_UNAVAILABLE",
            ) from exc
        finally:
            if owns_client:
                await client_to_use.aclose()
