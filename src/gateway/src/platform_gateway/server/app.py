"""Starlette ASGI Gateway application exposing /mcp using official MCP lowlevel Server runtime."""

import json
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from platform_gateway.adapters.http_dispatcher import HttpToolDispatcher
from platform_gateway.constants import (
    INTERNAL_HEADER_CORRELATION_ID,
    PROHIBITED_CALLER_HEADERS,
)
from platform_gateway.contracts.routing import GatewayRoutingTable
from platform_gateway.registry import GatewayBackendRegistry, create_default_routing_table
from platform_gateway.schemas import get_platform_tool_schemas
from platform_gateway.services.gateway_service import GatewayApplicationService
from platform_gateway.settings import GatewayAppSettings
from platform_observability.logging import get_logger
from platform_security.jwt import JwtAuthenticator
from platform_security.rbac import YamlPolicyEngine
from platform_security.sanitization import RecursiveOutputSanitizer

if TYPE_CHECKING:
    from platform_gateway.contracts.dispatch import GatewayDispatchResponse

logger = get_logger(__name__)


class StripInternalHeadersMiddleware:
    """Edge security middleware that unconditionally strips internal identity headers.

    Prevents external caller spoofing of X-User-ID, X-User-Role, X-Production-Write,
    X-Attachment-Access, and any header prefixed with x-security-.
    Also ensures the Accept header includes application/json and text/event-stream for MCP.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            cleaned_headers: list[tuple[bytes, bytes]] = []
            has_accept = False
            for header_name, header_val in scope.get("headers", []):
                lower_name = header_name.decode("latin1").lower()
                if lower_name in PROHIBITED_CALLER_HEADERS:
                    logger.warning(
                        "Stripped prohibited internal header from external request",
                        header=lower_name,
                    )
                    continue
                if lower_name.startswith("x-security-"):
                    logger.warning(
                        "Stripped prefixed security header from external request",
                        header=lower_name,
                    )
                    continue

                if lower_name == "accept":
                    has_accept = True
                    accept_val = header_val.decode("latin1")
                    if (
                        "text/event-stream" not in accept_val
                        or "application/json" not in accept_val
                    ):
                        cleaned_headers.append((b"accept", b"application/json, text/event-stream"))
                        continue

                cleaned_headers.append((header_name, header_val))

            if not has_accept:
                cleaned_headers.append((b"accept", b"application/json, text/event-stream"))

            scope["headers"] = cleaned_headers

        await self.app(scope, receive, send)


def _resolve_correlation_id(raw_id: str | None) -> str:
    """Generate or sanitize correlation ID."""
    if not raw_id or not raw_id.strip():
        return f"gw-corr-{uuid.uuid4()}"
    return raw_id.strip()


def create_gateway_server(
    service: GatewayApplicationService,
) -> tuple[Server, StreamableHTTPSessionManager]:
    """Create and configure official low-level MCP SDK Server and StreamableHTTPSessionManager."""
    server = Server("superoffice-ai-gateway", version="0.1.0")

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[types.Tool]:
        """Return the official 18-tool platform schemas."""
        return get_platform_tool_schemas()

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(
        name: str,
        arguments: dict[str, Any] | None,
    ) -> types.CallToolResult:
        """Process tool invocation through full GatewayApplicationService security pipeline."""
        req_ctx = server.request_context
        http_request: Request | None = getattr(req_ctx, "request", None)

        auth_header = http_request.headers.get("authorization") if http_request else None
        corr_id = _resolve_correlation_id(
            http_request.headers.get(INTERNAL_HEADER_CORRELATION_ID) if http_request else None
        )
        client_ip = http_request.client.host if http_request and http_request.client else None

        args = arguments or {}

        dispatch_res: GatewayDispatchResponse = await service.handle_tool_call(
            tool_name=name,
            arguments=args,
            authorization_header=auth_header,
            correlation_id=corr_id,
            client_ip=client_ip,
        )

        if dispatch_res.success:
            if isinstance(dispatch_res.result, str):
                text_content = dispatch_res.result
                structured_data = None
            else:
                text_content = json.dumps(dispatch_res.result, ensure_ascii=False)
                structured_data = (
                    dispatch_res.result
                    if (name == "investigate_incident" and isinstance(dispatch_res.result, dict))
                    else None
                )

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text_content)],
                structuredContent=structured_data,
                isError=False,
            )
        else:
            err_code = dispatch_res.error.error if dispatch_res.error else "TOOL_ERROR"
            err_msg = dispatch_res.error.message if dispatch_res.error else "Tool execution failed."
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"[{err_code}] {err_msg}")],
                isError=True,
            )

    session_manager = StreamableHTTPSessionManager(server, stateless=True)
    return server, session_manager


async def _execute_json_tool_call(
    service: GatewayApplicationService,
    params: dict[str, Any],
    request: Request,
    rpc_id: Any,
) -> JSONResponse:
    """Execute tool call for fallback JSON handler."""
    tool_name = params.get("name", "")
    tool_args = params.get("arguments", {})
    auth_header = request.headers.get("authorization")
    corr_id = _resolve_correlation_id(request.headers.get(INTERNAL_HEADER_CORRELATION_ID))
    client_ip = request.client.host if request.client else None

    dispatch_res = await service.handle_tool_call(
        tool_name=tool_name,
        arguments=tool_args,
        authorization_header=auth_header,
        correlation_id=corr_id,
        client_ip=client_ip,
    )

    if dispatch_res.success:
        if isinstance(dispatch_res.result, str):
            res_text = dispatch_res.result
            structured_data = None
        else:
            res_text = json.dumps(dispatch_res.result, ensure_ascii=False)
            structured_data = (
                dispatch_res.result
                if (tool_name == "investigate_incident" and isinstance(dispatch_res.result, dict))
                else None
            )
        result_payload: dict[str, Any] = {
            "content": [{"type": "text", "text": res_text}],
            "isError": False,
        }
        if structured_data is not None:
            result_payload["structuredContent"] = structured_data
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": result_payload,
            }
        )

    err_code = dispatch_res.error.error if dispatch_res.error else "TOOL_ERROR"
    err_msg = dispatch_res.error.message if dispatch_res.error else "Tool execution failed."
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "content": [{"type": "text", "text": f"[{err_code}] {err_msg}"}],
                "isError": True,
            },
        }
    )


def create_gateway_app(
    settings: GatewayAppSettings | None = None,
    service: GatewayApplicationService | None = None,
    routing_table: GatewayRoutingTable | None = None,
) -> Starlette:
    """Construct and configure the complete Starlette ASGI Gateway Application."""
    active_service = service
    if active_service is None:
        table = routing_table or create_default_routing_table()
        app_settings = settings or GatewayAppSettings()
        backend_reg = GatewayBackendRegistry(settings=app_settings)
        dispatcher = HttpToolDispatcher(backend_registry=backend_reg)
        jwt_auth = JwtAuthenticator(
            secret_or_key=app_settings.security.jwt_secret_key.get_secret_value(),
            algorithms=["HS256"],
        )
        rbac_engine = YamlPolicyEngine()
        sanitizer = RecursiveOutputSanitizer()

        active_service = GatewayApplicationService(
            routing_table=table,
            dispatcher=dispatcher,
            authenticator=jwt_auth,
            authorizer=rbac_engine,
            sanitizer=sanitizer,
        )

    _server, session_manager = create_gateway_server(active_service)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:  # noqa: ARG001
        async with session_manager.run():
            yield

    async def health_endpoint(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse({"status": "healthy", "service": "platform-gateway"})

    async def fallback_json_mcp_handler(request: Request) -> Response:
        """Handle direct /mcp JSON-RPC POST requests converting to standard MCP payloads."""
        try:
            body_bytes = await request.body()
            body_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error: invalid JSON"},
                },
                status_code=400,
            )

        rpc_id = body_json.get("id")
        method = body_json.get("method")
        params = body_json.get("params", {})

        if method == "initialize":
            client_proto = str(params.get("protocolVersion", "")).strip()
            supported = {"2024-11-05", "2025-03-26", "2025-11-25"}
            negotiated = client_proto if client_proto in supported else "2024-11-05"
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "protocolVersion": negotiated,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "superoffice-ai-gateway", "version": "0.1.0"},
                    },
                }
            )
        if method == "ping":
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": {}})
        if method == "tools/list":
            schemas = [t.model_dump(mode="json") for t in get_platform_tool_schemas()]
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": schemas}})
        if method == "tools/call":
            return await _execute_json_tool_call(active_service, params, request, rpc_id)

        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": f"Method '{method}' not found"},
            },
            status_code=404,
        )

    routes = [
        Route("/health", health_endpoint, methods=["GET"]),
        Route("/mcp/json", fallback_json_mcp_handler, methods=["POST"]),
        Mount("/mcp", app=session_manager.handle_request),
    ]

    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(StripInternalHeadersMiddleware)
    return app
