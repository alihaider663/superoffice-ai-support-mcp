"""Investigation MCP Server low-level runtime application exposing /mcp tools.

Official MCP Python SDK low-level Server boundary providing Streamable HTTP
stateless execution with safe, application-controlled input validation.
"""

import json
from typing import Any

from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import ValidationError as PydanticValidationError
from starlette.applications import Starlette
from starlette.routing import Route

from investigation_mcp.adapters.diagnostics_mcp_adapter import DiagnosticsMcpClientAdapter
from investigation_mcp.adapters.knowledge_mcp_adapter import KnowledgeMcpClientAdapter
from investigation_mcp.adapters.superoffice_mcp_adapter import SuperOfficeMcpClientAdapter
from investigation_mcp.contracts.dtos import (
    InvestigateIncidentRequestDTO,
    InvestigateIncidentResponseDTO,
)
from investigation_mcp.contracts.errors import InvestigationContractError
from investigation_mcp.contracts.mappers import (
    InvestigationRequestMapper,
    InvestigationResponseMapper,
)
from investigation_mcp.settings import InvestigationServerSettings
from platform_investigation import IncidentCorrelationEngine, InvestigationOrchestratorEngine
from platform_investigation.evaluator import HypothesisEvaluatorEngine
from platform_investigation.store import InMemoryInvestigationStore
from platform_investigation_service.ports import (
    DiagnosticsServicePort,
    KnowledgeServicePort,
    LogsServicePort,
    SuperOfficeServicePort,
)
from platform_investigation_service.service import InvestigationApplicationService
from platform_observability.logging import get_logger

logger = get_logger(__name__)

ALLOWED_BACKEND_HOSTS = [
    "localhost",
    "localhost:*",
    "127.0.0.1",
    "127.0.0.1:*",
    "testserver",
    "testserver:*",
    "investigation-backend",
    "investigation-backend:*",
    "investigation-server",
    "investigation-server:*",
    "investigation-internal",
    "investigation-internal:*",
]

TOOL_DESCRIPTION_INVESTIGATE_INCIDENT = (
    "Investigate support incidents by gathering read-only diagnostic evidence from "
    "SuperOffice CRM, MSSQL database diagnostics, application logs, and the knowledge base. "
    "Correlates events chronologically, evaluates working hypotheses against findings, "
    "and returns structured findings and source availability status. Requested sources "
    "may be unavailable, blocked, or unconfigured. The tool does not modify records, "
    "maintain durable investigation sessions, or perform automated state mutations."
)


def _format_validation_error(exc: Exception) -> str:
    """Format parameter validation error without leaking sensitive free-text values."""
    if isinstance(exc, PydanticValidationError):
        field_messages: list[str] = []
        for err in exc.errors(include_input=False, include_url=False):
            loc_parts = [str(part) for part in err.get("loc", ())]
            loc_str = ".".join(loc_parts)
            msg = err.get("msg", "Invalid value")
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, ") :]
            if loc_str:
                field_messages.append(f"Field '{loc_str}': {msg}")
            else:
                field_messages.append(msg)
        return f"Invalid investigation request: {'; '.join(field_messages)}"
    return f"Invalid investigation request: {exc}"


class EndpointSettings:
    """Wrapper exposing both MCP endpoint transport flags and application server settings."""

    stateless_http: bool = True
    streamable_http_path: str = "/mcp"

    def __init__(self, app_settings: InvestigationServerSettings) -> None:
        self._app_settings = app_settings

    def __getattr__(self, name: str) -> Any:
        return getattr(self._app_settings, name)


class InvestigationMcpServer(Server):
    """Official MCP Python SDK low-level Server boundary for Investigation MCP.

    Exposes the public read-only 'investigate_incident' tool over Streamable HTTP.
    Performs safe application-controlled validation with zero caller-input echoing.
    """

    def __init__(  # noqa: PLR0917
        self,
        service: InvestigationApplicationService | None = None,
        settings: InvestigationServerSettings | None = None,
        superoffice_service: SuperOfficeServicePort | None = None,
        diagnostics_service: DiagnosticsServicePort | None = None,
        knowledge_service: KnowledgeServicePort | None = None,
        logs_service: LogsServicePort | None = None,
    ) -> None:
        super().__init__("investigation-mcp-server")
        self.app_settings = settings or InvestigationServerSettings()
        self.settings = EndpointSettings(self.app_settings)
        self._service = service
        self._superoffice_service = superoffice_service
        self._diagnostics_service = diagnostics_service
        self._knowledge_service = knowledge_service
        self._logs_service = logs_service

        self._tools: list[Tool] = [
            Tool(
                name="investigate_incident",
                description=TOOL_DESCRIPTION_INVESTIGATE_INCIDENT,
                inputSchema=InvestigateIncidentRequestDTO.model_json_schema(by_alias=True),
                outputSchema=InvestigateIncidentResponseDTO.model_json_schema(by_alias=True),
            )
        ]

        self._register_handlers()
        self._session_manager: StreamableHTTPSessionManager | None = None

    def _register_handlers(self) -> None:
        """Register low-level MCP request handlers."""

        @super().list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
        async def _handle_list_tools() -> list[Tool]:
            return list(self._tools)

        @super().call_tool(validate_input=False)  # type: ignore[untyped-decorator]
        async def _handle_call_tool(name: str, arguments: dict[str, Any] | None) -> CallToolResult:
            return await self._execute_tool(name, arguments)

    async def _execute_tool(self, name: str, arguments: dict[str, Any] | None) -> CallToolResult:
        """Execute tool request with application-controlled validation and error formatting."""
        if name != "investigate_incident":
            return CallToolResult(
                content=[TextContent(type="text", text=f"Unknown tool: '{name}'.")],
                isError=True,
            )

        raw_args = arguments if arguments is not None else {}

        # 1. Validate public request DTO
        try:
            public_request = InvestigateIncidentRequestDTO.model_validate(raw_args)
        except (PydanticValidationError, ValueError) as exc:
            logger.warning(
                "Investigation request validation failed",
                error_code="PUBLIC_REQUEST_VALIDATION_FAILED",
            )
            safe_msg = _format_validation_error(exc)
            return CallToolResult(
                content=[TextContent(type="text", text=safe_msg)],
                isError=True,
            )

        # 2. Pipeline execution: map, orchestrate, serialize
        internal_err: str | None = None
        public_response: InvestigateIncidentResponseDTO | None = None
        try:
            internal_request = InvestigationRequestMapper.to_internal_request(public_request)
            if self._service is not None:
                internal_result = await self._service.investigate(internal_request)
            else:
                so_port = self._superoffice_service or SuperOfficeMcpClientAdapter(
                    base_url=str(self.app_settings.superoffice_mcp_url)
                )
                diag_port = self._diagnostics_service or DiagnosticsMcpClientAdapter(
                    base_url=str(self.app_settings.diagnostics_mcp_url)
                )
                kb_port = self._knowledge_service or (
                    KnowledgeMcpClientAdapter(base_url=str(self.app_settings.knowledge_mcp_url))
                    if self.app_settings.knowledge_mcp_url is not None
                    else None
                )
                logs_port = self._logs_service or (
                    diag_port if isinstance(diag_port, LogsServicePort) else None
                )
                req_store = InMemoryInvestigationStore()
                req_orchestrator = InvestigationOrchestratorEngine(store=req_store)
                req_correlator = IncidentCorrelationEngine()
                req_evaluator = HypothesisEvaluatorEngine()
                req_service = InvestigationApplicationService(
                    orchestrator=req_orchestrator,
                    superoffice_service=so_port,
                    diagnostics_service=diag_port,
                    knowledge_service=kb_port,
                    logs_service=logs_port,
                    correlator=req_correlator,
                    evaluator=req_evaluator,
                )
                internal_result = await req_service.investigate(internal_request)

            public_response = InvestigationResponseMapper.to_public_response(internal_result)
        except InvestigationContractError:
            logger.error(
                "Investigation mapping integrity failed",
                error_code="MAPPING_INTEGRITY_FAILED",
            )
            internal_err = "An unexpected internal error occurred during incident investigation."
        except Exception:
            logger.error(
                "Investigation execution failed",
                error_code="EXECUTION_FAILED",
            )
            internal_err = "An unexpected internal error occurred during incident investigation."

        if internal_err or public_response is None:
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="An unexpected internal error occurred during incident investigation.",
                    )
                ],
                isError=True,
            )

        logger.info(
            "Investigation tool completed successfully",
            outcome_count=len(public_response.source_outcomes),
            evidence_count=len(public_response.evidence),
            has_evaluation=public_response.hypothesis_evaluation is not None,
        )
        response_dict = public_response.model_dump(mode="json")
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(response_dict, indent=2))],
            structuredContent=response_dict,
            isError=False,
        )

    async def list_tools(self) -> list[Tool]:
        """List registered MCP tools."""
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> CallToolResult:  # type: ignore[override]
        """Call registered MCP tool."""
        return await self._execute_tool(name, arguments)

    @property
    def session_manager(self) -> StreamableHTTPSessionManager:
        """Streamable HTTP session manager."""
        if self._session_manager is None:
            self._session_manager = StreamableHTTPSessionManager(
                app=self,
                security_settings=TransportSecuritySettings(
                    enable_dns_rebinding_protection=True,
                    allowed_hosts=ALLOWED_BACKEND_HOSTS,
                ),
                stateless=self.settings.stateless_http,
            )
        return self._session_manager

    def streamable_http_app(self) -> Starlette:
        """Return Starlette ASGI application for Streamable HTTP transport."""
        mgr = self.session_manager

        class StreamableHTTPASGIApp:
            def __init__(self, manager: StreamableHTTPSessionManager) -> None:
                self.manager = manager

            async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                await self.manager.handle_request(scope, receive, send)

        asgi_app = StreamableHTTPASGIApp(mgr)
        return Starlette(
            debug=False,
            routes=[Route(self.settings.streamable_http_path, endpoint=asgi_app)],
            lifespan=lambda _app: mgr.run(),
        )


def create_investigation_mcp_server(  # noqa: PLR0917
    service: InvestigationApplicationService | None = None,
    settings: InvestigationServerSettings | None = None,
    superoffice_service: SuperOfficeServicePort | None = None,
    diagnostics_service: DiagnosticsServicePort | None = None,
    knowledge_service: KnowledgeServicePort | None = None,
    logs_service: LogsServicePort | None = None,
) -> InvestigationMcpServer:
    """Instantiate and configure the official low-level MCP Investigation server.

    Hosts the Layer-1 Streamable HTTP endpoint and registers the public
    read-only 'investigate_incident' tool.
    """
    return InvestigationMcpServer(
        service=service,
        settings=settings,
        superoffice_service=superoffice_service,
        diagnostics_service=diagnostics_service,
        knowledge_service=knowledge_service,
        logs_service=logs_service,
    )


def create_app(  # noqa: PLR0917
    settings: InvestigationServerSettings | None = None,
    service: InvestigationApplicationService | None = None,
    superoffice_service: SuperOfficeServicePort | None = None,
    diagnostics_service: DiagnosticsServicePort | None = None,
    knowledge_service: KnowledgeServicePort | None = None,
    logs_service: LogsServicePort | None = None,
) -> Starlette:
    """Create the Starlette ASGI application for Investigation MCP Server."""
    server = create_investigation_mcp_server(
        service=service,
        settings=settings,
        superoffice_service=superoffice_service,
        diagnostics_service=diagnostics_service,
        knowledge_service=knowledge_service,
        logs_service=logs_service,
    )
    return server.streamable_http_app()
