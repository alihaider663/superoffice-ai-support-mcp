"""Deterministic in-memory FakeGatewayDispatcher for offline contract testing."""

from platform_gateway.contracts.dispatch import (
    GatewayDispatchRequest,
    GatewayDispatchResponse,
    SanitizedErrorPayload,
)
from platform_gateway.contracts.errors import GatewayDispatchError
from platform_gateway.contracts.routing import ToolRouteDefinition
from platform_gateway.contracts.types import JsonValue


class FakeGatewayDispatcher:
    """Deterministic in-memory implementation of StreamableHttpDispatcher Protocol."""

    def __init__(self) -> None:
        self._responses: dict[str, GatewayDispatchResponse] = {}
        self._dispatched: list[tuple[ToolRouteDefinition, GatewayDispatchRequest]] = []
        self._should_fail: bool = False

    # Seed and configuration helpers
    def set_response(self, tool_name: str, response: GatewayDispatchResponse) -> None:
        """Seed a pre-configured response for a specific tool."""
        self._responses[tool_name] = response

    def set_default_success(self, tool_name: str, result: JsonValue) -> None:
        """Convenience helper to seed a successful JSON result."""
        self._responses[tool_name] = GatewayDispatchResponse(
            tool_name=tool_name,
            success=True,
            result=result,
            error=None,
            # Placeholder correlation_id is replaced with request.correlation_id during dispatch
            correlation_id="SEED-PLACEHOLDER",
        )

    def set_error(self, tool_name: str, error_code: str, message: str) -> None:
        """Convenience helper to seed a sanitized error response."""
        self._responses[tool_name] = GatewayDispatchResponse(
            tool_name=tool_name,
            success=False,
            result=None,
            error=SanitizedErrorPayload(
                error=error_code,
                message=message,
            ),
            # Placeholder correlation_id is replaced with request.correlation_id during dispatch
            correlation_id="SEED-PLACEHOLDER",
        )

    def set_should_fail(self, should_fail: bool) -> None:
        """Simulate transport failure (e.g. downstream server unreachable)."""
        self._should_fail = should_fail

    def get_dispatched_requests(
        self,
    ) -> list[tuple[ToolRouteDefinition, GatewayDispatchRequest]]:
        """Return history of dispatched requests for assertion."""
        return list(self._dispatched)

    # Protocol implementation
    async def dispatch(
        self,
        route: ToolRouteDefinition,
        request: GatewayDispatchRequest,
    ) -> GatewayDispatchResponse:
        """Dispatch request to in-memory fake destination."""
        if self._should_fail:
            raise GatewayDispatchError(
                f"Simulated transport failure reaching {route.target_server.value}."
            )

        self._dispatched.append((route, request))

        if request.tool_name in self._responses:
            res = self._responses[request.tool_name]
            return GatewayDispatchResponse(
                tool_name=res.tool_name,
                success=res.success,
                result=res.result,
                error=res.error,
                correlation_id=request.correlation_id,
            )

        # Default echo response if not explicitly seeded
        return GatewayDispatchResponse(
            tool_name=request.tool_name,
            success=True,
            result={
                "echo_arguments": request.arguments,
                "target_server": route.target_server.value,
            },
            error=None,
            correlation_id=request.correlation_id,
        )
