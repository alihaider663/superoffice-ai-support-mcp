"""Gateway application service orchestrating security, RBAC, rate-limiting, and dispatch."""

from typing import Any
from uuid import uuid4

from platform_core.errors import AuthenticationError
from platform_gateway.contracts.dispatch import (
    GatewayDispatchRequest,
    GatewayDispatchResponse,
    SanitizedErrorPayload,
)
from platform_gateway.contracts.errors import GatewayDispatchError
from platform_gateway.contracts.interfaces import StreamableHttpDispatcher
from platform_gateway.contracts.routing import GatewayRoutingTable
from platform_observability.audit import AuditContext, AuditSink
from platform_security.interfaces import Authenticator, OutputSanitizer, PolicyEngine
from platform_security.rate_limiting import SlidingWindowRateLimiter, format_rate_limit_key


class GatewayApplicationService:
    """Central Gateway orchestration service enforcing security perimeter invariants.

    Enforces:
    1. Inbound correlation ID lifecycle.
    2. Cryptographic JWT Bearer token authentication (ADR 009).
    3. Target tool routing lookup.
    4. Deterministic deny-by-default YAML RBAC (ADR 010) with cumulative role and privilege checks.
    5. Sliding-window rate limiting.
    6. Structured security audit emission.
    7. Downstream Streamable HTTP dispatch (ADR 007).
    8. Recursive output sanitization / PII scrubbing.
    9. Global safe error mapping without credential or traceback leakage.
    """

    def __init__(
        self,
        routing_table: GatewayRoutingTable,
        dispatcher: StreamableHttpDispatcher,
        authenticator: Authenticator,
        authorizer: PolicyEngine,
        *,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        audit_sink: AuditSink | None = None,
        sanitizer: OutputSanitizer | None = None,
    ) -> None:
        self._routing_table = routing_table
        self._dispatcher = dispatcher
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._rate_limiter = rate_limiter
        self._audit_sink = audit_sink
        self._sanitizer = sanitizer

    async def handle_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        authorization_header: str | None = None,
        correlation_id: str | None = None,
        client_ip: str | None = None,
    ) -> GatewayDispatchResponse:
        """Process inbound MCP tool call through full Gateway security and dispatch pipeline."""
        corr_id = (
            correlation_id.strip() if correlation_id and correlation_id.strip() else str(uuid4())
        )
        normalized_args: dict[str, Any] = arguments or {}
        audit_ctx = AuditContext(
            event_type="TOOL_EXECUTION",
            action=tool_name,
            sink=self._audit_sink,
        )

        # 1. JWT Authentication
        if not authorization_header or not authorization_header.strip():
            await audit_ctx.record_failure(
                reason="AUTHENTICATION_REQUIRED",
                metadata_summary={"error": "Missing Authorization header"},
            )
            return GatewayDispatchResponse(
                tool_name=tool_name,
                success=False,
                result=None,
                error=SanitizedErrorPayload(
                    error="AUTHENTICATION_REQUIRED",
                    message="Authentication token required.",
                    correlation_id=corr_id,
                ),
                correlation_id=corr_id,
            )

        try:
            sec_ctx = await self._authenticator.authenticate(authorization_header)
        except AuthenticationError:
            await audit_ctx.record_failure(
                reason="INVALID_TOKEN",
                metadata_summary={"error": "JWT verification failed"},
            )
            return GatewayDispatchResponse(
                tool_name=tool_name,
                success=False,
                result=None,
                error=SanitizedErrorPayload(
                    error="INVALID_TOKEN",
                    message="Authentication failed. Invalid, expired, or untrusted token.",
                    correlation_id=corr_id,
                ),
                correlation_id=corr_id,
            )

        audit_ctx.user_id = sec_ctx.principal.user_id
        audit_ctx.role = sec_ctx.principal.role

        # 2. Tool Route Verification
        if not self._routing_table.has_route(tool_name):
            await audit_ctx.record_failure(
                reason="ROUTE_NOT_FOUND",
                metadata_summary={"tool_name": tool_name},
            )
            return GatewayDispatchResponse(
                tool_name=tool_name,
                success=False,
                result=None,
                error=SanitizedErrorPayload(
                    error="ROUTE_NOT_FOUND",
                    message=f"Tool '{tool_name}' is not registered in the routing table.",
                    correlation_id=corr_id,
                ),
                correlation_id=corr_id,
            )

        route = self._routing_table.get_route(tool_name)
        audit_ctx.target_server = route.target_server.value

        # 3. YAML RBAC & Privilege Evaluation
        decision = self._authorizer.evaluate_policy(
            principal_role=sec_ctx.principal.role,
            tool_name=tool_name,
            context_attributes=sec_ctx.attributes,
        )
        if not decision.is_allowed:
            denial_code = decision.denial_code or "FORBIDDEN"
            await audit_ctx.record_failure(
                reason=denial_code,
                metadata_summary={"denial_reason": decision.reason},
            )
            return GatewayDispatchResponse(
                tool_name=tool_name,
                success=False,
                result=None,
                error=SanitizedErrorPayload(
                    error=denial_code,
                    message=f"Access denied for tool '{tool_name}': {decision.reason}",
                    correlation_id=corr_id,
                ),
                correlation_id=corr_id,
            )

        # 4. Rate Limiting
        if self._rate_limiter is not None:
            rate_key = format_rate_limit_key(
                identity=sec_ctx.principal.user_id,
                tool_name=tool_name,
                client_ip=client_ip,
            )
            if not self._rate_limiter.is_allowed(rate_key):
                await audit_ctx.record_failure(
                    reason="RATE_LIMIT_EXCEEDED",
                    metadata_summary={"identity": sec_ctx.principal.user_id},
                )
                return GatewayDispatchResponse(
                    tool_name=tool_name,
                    success=False,
                    result=None,
                    error=SanitizedErrorPayload(
                        error="RATE_LIMIT_EXCEEDED",
                        message="Rate limit exceeded for tool request. Please retry later.",
                        correlation_id=corr_id,
                    ),
                    correlation_id=corr_id,
                )

        # 5. Downstream Dispatch
        dispatch_req = GatewayDispatchRequest(
            tool_name=tool_name,
            arguments=normalized_args,
            security_context=sec_ctx,
            correlation_id=corr_id,
        )

        try:
            dispatch_res = await self._dispatcher.dispatch(
                route=route,
                request=dispatch_req,
            )
        except GatewayDispatchError:
            dispatch_res = GatewayDispatchResponse(
                tool_name=tool_name,
                success=False,
                result=None,
                error=SanitizedErrorPayload(
                    error="UPSTREAM_ERROR",
                    message="Downstream service failed to process request.",
                    correlation_id=corr_id,
                ),
                correlation_id=corr_id,
            )

        # 6. Global Response Sanitization
        final_result = dispatch_res.result
        if dispatch_res.success and final_result is not None and self._sanitizer is not None:
            final_result = self._sanitizer.sanitize(final_result)
            dispatch_res = GatewayDispatchResponse(
                tool_name=tool_name,
                success=True,
                result=final_result,
                error=None,
                correlation_id=corr_id,
            )

        # 7. Audit Completion
        if dispatch_res.success:
            await audit_ctx.record_success(target_resource=tool_name)
        else:
            err_code = dispatch_res.error.error if dispatch_res.error else "DISPATCH_FAILED"
            await audit_ctx.record_failure(reason=err_code)

        return dispatch_res

    @property
    def dispatcher(self) -> StreamableHttpDispatcher:
        """Access the underlying dispatcher."""
        return self._dispatcher

    async def aclose(self) -> None:
        """Gracefully release gateway resources including connection pools."""
        if hasattr(self._dispatcher, "aclose"):
            await self._dispatcher.aclose()
