"""Knowledge Base MCP Server FastMCP runtime application exposing /mcp tools."""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnownIssueSearchCriteriaDTO,
)
from kb_mcp.contracts.errors import KnowledgeBackendNotConfiguredError
from kb_mcp.contracts.interfaces import KnowledgeRepository
from kb_mcp.services.knowledge_service import KnowledgeApplicationService
from kb_mcp.settings import KnowledgeServerSettings

ALLOWED_BACKEND_HOSTS = [
    "localhost",
    "localhost:*",
    "127.0.0.1",
    "127.0.0.1:*",
    "testserver",
    "testserver:*",
    "kb-backend",
    "kb-backend:*",
    "kb-server",
    "kb-server:*",
    "kb-internal",
    "kb-internal:*",
]


def create_knowledge_mcp_server(
    service: KnowledgeApplicationService | None = None,
    repository: KnowledgeRepository | None = None,
) -> FastMCP:
    """Instantiate and configure the official FastMCP Knowledge server."""
    mcp_server = FastMCP(
        name="knowledge-mcp-server",
        streamable_http_path="/mcp",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=ALLOWED_BACKEND_HOSTS,
        ),
    )

    app_service = service or (
        KnowledgeApplicationService(repository=repository) if repository else None
    )

    @mcp_server.tool(
        name="search_knowledge",
        description="Search sanitized knowledge base and runbooks",
    )
    async def search_knowledge(query_text: str, max_results: int = 5) -> list[dict[str, Any]]:
        if app_service is None:
            raise KnowledgeBackendNotConfiguredError("Knowledge backend is not configured.")
        criteria = KnowledgeSearchCriteriaDTO(query_text=query_text, limit=max_results)
        chunks = await app_service.search_knowledge(criteria)
        return [c.model_dump(mode="json") for c in chunks]

    @mcp_server.tool(name="get_runbook", description="Retrieve specific runbook by ID")
    async def get_runbook(runbook_id: str) -> dict[str, Any]:
        if app_service is None:
            raise KnowledgeBackendNotConfiguredError("Knowledge backend is not configured.")
        rb = await app_service.get_runbook(runbook_id)
        return rb.model_dump(mode="json")

    @mcp_server.tool(name="find_known_issues", description="Find matching known issue articles")
    async def find_known_issues(query_text: str, max_results: int = 5) -> list[dict[str, Any]]:
        if app_service is None:
            raise KnowledgeBackendNotConfiguredError("Knowledge backend is not configured.")
        criteria = KnownIssueSearchCriteriaDTO(query_text=query_text, limit=max_results)
        issues = await app_service.find_known_issues(criteria)
        return [i.model_dump(mode="json") for i in issues]

    return mcp_server


def create_app(
    settings: KnowledgeServerSettings | None = None,  # noqa: ARG001
    service: KnowledgeApplicationService | None = None,
    repository: KnowledgeRepository | None = None,
) -> Starlette:
    """Create the Starlette ASGI application for Knowledge MCP Server."""
    server = create_knowledge_mcp_server(service=service, repository=repository)
    return server.streamable_http_app()
