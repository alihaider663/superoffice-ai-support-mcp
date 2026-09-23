"""Streamable HTTP Tool Dispatcher implementation using official MCP SDK Client."""

import json
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

from platform_core.errors import TimeoutError
from platform_gateway.constants import (
    INTERNAL_HEADER_ATTACHMENT_ACCESS,
    INTERNAL_HEADER_CORRELATION_ID,
    INTERNAL_HEADER_PRODUCTION_WRITE,
    INTERNAL_HEADER_USER_ID,
    INTERNAL_HEADER_USER_ROLE,
)
from platform_gateway.contracts.dispatch import (
    GatewayDispatchRequest,
    GatewayDispatchResponse,
    SanitizedErrorPayload,
)
from platform_gateway.contracts.interfaces import StreamableHttpDispatcher
from platform_gateway.contracts.routing import TargetServer, ToolRouteDefinition
from platform_gateway.registry import GatewayBackendRegistry
from platform_observability.logging import get_logger

logger = get_logger(__name__)


class PooledTransport(httpx.AsyncBaseTransport):
    """Passthrough transport preventing per-request client.aclose() from closing pool."""

    def __init__(self, underlying: httpx.AsyncBaseTransport) -> None:
        self._underlying = underlying

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._underlying.handle_async_request(request)

    async def aclose(self) -> None:
        # Keep underlying connection pool open across requests
        pass


class HttpToolDispatcher(StreamableHttpDispatcher):
    """Production Streamable HTTP dispatcher communicating with downstream MCP server backends.

    Enforces:
    - Target server URL resolution via trusted GatewayBackendRegistry (anti-SSRF).
    - Trusted identity context injection via sanitized internal headers.
    - Official MCP SDK streamable_http_client and ClientSession protocol lifecycle.
    - Persistent HTTP keep-alive connection pooling across dispatches.
    - Bounded transport timeouts and safe error mapping into SanitizedErrorPayload.
    """

    def __init__(
        self,
        backend_registry: GatewayBackendRegistry,
        http_client: httpx.AsyncClient | None = None,
        *,
        default_timeout_seconds: float = 30.0,
        limits: httpx.Limits | None = None,
    ) -> None:
        self._backend_registry = backend_registry
        self._http_client = http_client
        self._default_timeout_seconds = default_timeout_seconds
        self._limits = limits or httpx.Limits(
            max_keepalive_connections=20,
            max_connections=50,
            keepalive_expiry=30.0,
        )
        self._transport: httpx.AsyncHTTPTransport | None = (
            None if http_client is not None else httpx.AsyncHTTPTransport(limits=self._limits)
        )

    def _build_trusted_headers(
        self,
        request: GatewayDispatchRequest,
        target_server: TargetServer | None = None,
    ) -> dict[str, str]:
        """Construct trusted internal headers derived exclusively from verified Gateway context.

        For TargetServer.INVESTIGATION: Minimal headers only (Accept transport header).
        Zero internal user/role/privilege headers are forwarded.
        """
        if target_server == TargetServer.INVESTIGATION:
            return {
                "Accept": "application/json, text/event-stream",
            }

        sec_ctx = request.security_context
        prod_write = bool(sec_ctx.attributes.get("production_write", False))
        attach_access = bool(sec_ctx.attributes.get("attachment_access", False))

        return {
            "Accept": "application/json, text/event-stream",
            INTERNAL_HEADER_CORRELATION_ID: request.correlation_id,
            INTERNAL_HEADER_USER_ID: sec_ctx.principal.user_id,
            INTERNAL_HEADER_USER_ROLE: sec_ctx.principal.role,
            INTERNAL_HEADER_PRODUCTION_WRITE: str(prod_write).lower(),
            INTERNAL_HEADER_ATTACHMENT_ACCESS: str(attach_access).lower(),
        }

    def _extract_tool_result_payload(self, tool_result: CallToolResult) -> Any:
        """Extract Python data structure from official CallToolResult."""
        if tool_result.structuredContent is not None:
            return tool_result.structuredContent

        texts: list[str] = []
        for item in tool_result.content:
            if isinstance(item, TextContent):
                texts.append(item.text)

        joined_text = "\n".join(texts).strip()
        if not joined_text:
            return {}

        try:
            return json.loads(joined_text)
        except json.JSONDecodeError:
            return {"raw_text": joined_text}

    def _extract_tool_error_message(self, tool_result: CallToolResult) -> str:
        """Extract human-readable error string from error CallToolResult."""
        texts: list[str] = []
        for item in tool_result.content:
            if isinstance(item, TextContent):
                texts.append(item.text)

        msg = "\n".join(texts).strip()
        return msg or "Downstream MCP tool returned an error result."

    async def dispatch(
        self,
        route: ToolRouteDefinition,
        request: GatewayDispatchRequest,
    ) -> GatewayDispatchResponse:
        """Dispatch tool invocation downstream using official MCP streamable_http_client."""
        try:
            server_url = self._backend_registry.get_server_url(route.target_server)
        except KeyError:
            err_msg = f"No registered base URL for target server '{route.target_server.value}'."
            return GatewayDispatchResponse(
                tool_name=request.tool_name,
                success=False,
                result=None,
                error=SanitizedErrorPayload(
                    error="GATEWAY_ROUTE_UNCONFIGURED",
                    message=err_msg,
                ),
                correlation_id=request.correlation_id,
            )

        endpoint_url = f"{server_url}{route.endpoint_path}"
        trusted_headers = self._build_trusted_headers(request, route.target_server)

        timeout_config = httpx.Timeout(self._default_timeout_seconds)
        client_to_use: httpx.AsyncClient | None = self._http_client
        owns_client = False

        if client_to_use is None:
            transport_to_use = (
                PooledTransport(self._transport)
                if self._transport is not None
                else httpx.AsyncHTTPTransport(limits=self._limits)
            )
            client_to_use = httpx.AsyncClient(
                transport=transport_to_use,
                headers=trusted_headers,
                timeout=timeout_config,
                follow_redirects=False,
            )
            owns_client = True

        try:
            if not owns_client:
                for h in (
                    INTERNAL_HEADER_CORRELATION_ID,
                    INTERNAL_HEADER_USER_ID,
                    INTERNAL_HEADER_USER_ROLE,
                    INTERNAL_HEADER_PRODUCTION_WRITE,
                    INTERNAL_HEADER_ATTACHMENT_ACCESS,
                ):
                    client_to_use.headers.pop(h, None)
                for k, v in trusted_headers.items():
                    client_to_use.headers[k] = v

            async with (
                streamable_http_client(
                    endpoint_url,
                    http_client=client_to_use,
                ) as (read_stream, write_stream, _),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                tool_result: CallToolResult = await session.call_tool(
                    name=request.tool_name,
                    arguments=request.arguments,
                )

                if tool_result.isError:
                    err_msg = self._extract_tool_error_message(tool_result)
                    return GatewayDispatchResponse(
                        tool_name=request.tool_name,
                        success=False,
                        result=None,
                        error=SanitizedErrorPayload(
                            error="DOWNSTREAM_TOOL_ERROR",
                            message=err_msg,
                        ),
                        correlation_id=request.correlation_id,
                    )

                parsed_result = self._extract_tool_result_payload(tool_result)
                return GatewayDispatchResponse(
                    tool_name=request.tool_name,
                    success=True,
                    result=parsed_result,
                    error=None,
                    correlation_id=request.correlation_id,
                )

        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning(
                "Downstream MCP dispatch timed out",
                tool_name=request.tool_name,
                server=route.target_server.value,
                endpoint=endpoint_url,
                error=str(exc),
            )
            return GatewayDispatchResponse(
                tool_name=request.tool_name,
                success=False,
                result=None,
                error=SanitizedErrorPayload(
                    error="GATEWAY_DOWNSTREAM_TIMEOUT",
                    message="The downstream backend service timed out while processing request.",
                ),
                correlation_id=request.correlation_id,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning(
                "Downstream MCP server returned HTTP error status",
                tool_name=request.tool_name,
                status_code=status,
                endpoint=endpoint_url,
            )
            return GatewayDispatchResponse(
                tool_name=request.tool_name,
                success=False,
                result=None,
                error=SanitizedErrorPayload(
                    error="GATEWAY_DOWNSTREAM_UNAVAILABLE",
                    message=f"Downstream server returned HTTP status {status}.",
                ),
                correlation_id=request.correlation_id,
            )
        except Exception as exc:
            logger.error(
                "Downstream MCP dispatch failed",
                tool_name=request.tool_name,
                server=route.target_server.value,
                endpoint=endpoint_url,
                error=str(exc),
            )
            return GatewayDispatchResponse(
                tool_name=request.tool_name,
                success=False,
                result=None,
                error=SanitizedErrorPayload(
                    error="GATEWAY_DOWNSTREAM_UNAVAILABLE",
                    message="Downstream service is currently unavailable.",
                ),
                correlation_id=request.correlation_id,
            )
        finally:
            if owns_client:
                await client_to_use.aclose()

    async def aclose(self) -> None:
        """Close persistent HTTP transport pool."""
        if self._transport is not None:
            await self._transport.aclose()

