"""SuperOffice MCP Server FastMCP runtime application exposing /mcp tools."""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from so_mcp.adapters.factory import create_superoffice_client
from so_mcp.contracts.dtos import (
    CompanySearchCriteriaDTO,
    PersonSearchCriteriaDTO,
    TicketSearchCriteriaDTO,
)
from so_mcp.contracts.errors import SuperOfficeIntegrationError
from so_mcp.contracts.interfaces import SuperOfficeClient
from so_mcp.services.ticket_service import SuperOfficeApplicationService
from so_mcp.settings import SuperOfficeServerSettings

ALLOWED_BACKEND_HOSTS = [
    "localhost",
    "localhost:*",
    "127.0.0.1",
    "127.0.0.1:*",
    "testserver",
    "testserver:*",
    "so-backend",
    "so-backend:*",
    "so-server",
    "so-server:*",
    "so-internal",
    "so-internal:*",
]


def create_superoffice_mcp_server(
    service: SuperOfficeApplicationService | None = None,
    client: SuperOfficeClient | None = None,
) -> FastMCP:
    """Instantiate and configure the official FastMCP SuperOffice server.

    Registers exactly the 8 approved read-only SuperOffice operations.
    Write and raw attachment content operations are prohibited and deferred.
    """
    mcp_server = FastMCP(
        name="superoffice-mcp-server",
        streamable_http_path="/mcp",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=ALLOWED_BACKEND_HOSTS,
        ),
    )

    app_service = service or (SuperOfficeApplicationService(client=client) if client else None)

    @mcp_server.tool(name="get_ticket", description="Get basic ticket summary and status")
    async def get_ticket(ticket_id: int) -> dict[str, Any]:
        if app_service is None:
            raise SuperOfficeIntegrationError(
                "SuperOffice service is not configured or unavailable.",
                error_code="SUPEROFFICE_SERVICE_UNCONFIGURED",
            )
        res = await app_service.get_ticket(ticket_id)
        return res.model_dump(mode="json")

    @mcp_server.tool(
        name="search_tickets",
        description="Search tickets by title, category, or status",
    )
    async def search_tickets(
        title: str | None = None,  # noqa: ARG001
        category: str | None = None,  # noqa: ARG001
        status: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if app_service is None:
            raise SuperOfficeIntegrationError(
                "SuperOffice service is not configured or unavailable.",
                error_code="SUPEROFFICE_SERVICE_UNCONFIGURED",
            )
        criteria = TicketSearchCriteriaDTO(status=status, page_size=limit)
        res = await app_service.search_tickets(criteria)
        return res.model_dump(mode="json")

    @mcp_server.tool(
        name="get_ticket_messages",
        description="Get ticket message history",
    )
    async def get_ticket_messages(
        ticket_id: int,
        limit: int = 20,  # noqa: ARG001
    ) -> list[dict[str, Any]]:
        if app_service is None:
            raise SuperOfficeIntegrationError(
                "SuperOffice service is not configured or unavailable.",
                error_code="SUPEROFFICE_SERVICE_UNCONFIGURED",
            )
        msgs = await app_service.get_ticket_messages(ticket_id)
        return [m.model_dump(mode="json") for m in msgs]

    @mcp_server.tool(
        name="list_attachments",
        description="List attachment metadata without raw content",
    )
    async def list_attachments(ticket_id: int) -> list[dict[str, Any]]:
        if app_service is None:
            raise SuperOfficeIntegrationError(
                "SuperOffice service is not configured or unavailable.",
                error_code="SUPEROFFICE_SERVICE_UNCONFIGURED",
            )
        atts = await app_service.list_attachments(ticket_id)
        return [a.model_dump(mode="json") for a in atts]

    @mcp_server.tool(name="get_company", description="Retrieve customer company details")
    async def get_company(contact_id: int) -> dict[str, Any]:
        if app_service is None:
            raise SuperOfficeIntegrationError(
                "SuperOffice service is not configured or unavailable.",
                error_code="SUPEROFFICE_SERVICE_UNCONFIGURED",
            )
        res = await app_service.get_company(contact_id)
        return res.model_dump(mode="json")

    @mcp_server.tool(name="find_companies", description="Find companies matching criteria")
    async def find_companies(
        name: str | None = None,
        category: str | None = None,  # noqa: ARG001
        limit: int = 10,
    ) -> dict[str, Any]:
        if app_service is None:
            raise SuperOfficeIntegrationError(
                "SuperOffice service is not configured or unavailable.",
                error_code="SUPEROFFICE_SERVICE_UNCONFIGURED",
            )
        criteria = CompanySearchCriteriaDTO(name=name, page_size=limit)
        res = await app_service.find_companies(criteria)
        return res.model_dump(mode="json")

    @mcp_server.tool(name="get_person", description="Retrieve customer contact person details")
    async def get_person(person_id: int) -> dict[str, Any]:
        if app_service is None:
            raise SuperOfficeIntegrationError(
                "SuperOffice service is not configured or unavailable.",
                error_code="SUPEROFFICE_SERVICE_UNCONFIGURED",
            )
        res = await app_service.get_person(person_id)
        return res.model_dump(mode="json")

    @mcp_server.tool(name="find_persons", description="Find contact persons matching criteria")
    async def find_persons(
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        contact_id: int | None = None,  # noqa: ARG001
        limit: int = 10,
    ) -> dict[str, Any]:
        if app_service is None:
            raise SuperOfficeIntegrationError(
                "SuperOffice service is not configured or unavailable.",
                error_code="SUPEROFFICE_SERVICE_UNCONFIGURED",
            )
        criteria = PersonSearchCriteriaDTO(
            name=f"{first_name or ''} {last_name or ''}".strip() or None,
            email=email,
            page_size=limit,
        )
        res = await app_service.find_persons(criteria)
        return res.model_dump(mode="json")

    return mcp_server


def create_app(
    settings: SuperOfficeServerSettings | None = None,
    service: SuperOfficeApplicationService | None = None,
    client: SuperOfficeClient | None = None,
) -> Starlette:
    """Create the Starlette ASGI application for SuperOffice MCP Server."""
    active_service = service
    if active_service is None:
        if client is not None:
            active_service = SuperOfficeApplicationService(client=client)
        else:
            active_settings = settings or SuperOfficeServerSettings()
            active_client = create_superoffice_client(active_settings)
            active_service = SuperOfficeApplicationService(client=active_client)

    server = create_superoffice_mcp_server(service=active_service)
    return server.streamable_http_app()
