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
from so_mcp.sync.service import SuperOfficeCodebaseSyncService

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
    sync_service: SuperOfficeCodebaseSyncService | None = None,
) -> FastMCP:
    """Instantiate and configure the official FastMCP SuperOffice server.

    Registers approved SuperOffice operations and codebase sync tools.
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
        title: str | None = None,
        category: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if app_service is None:
            raise SuperOfficeIntegrationError(
                "SuperOffice service is not configured or unavailable.",
                error_code="SUPEROFFICE_SERVICE_UNCONFIGURED",
            )
        criteria = TicketSearchCriteriaDTO(
            title=title,
            category=category,
            status=status,
            page_size=limit,
        )
        res = await app_service.search_tickets(criteria)
        return res.model_dump(mode="json")

    @mcp_server.tool(
        name="get_ticket_messages",
        description="Get ticket message history",
    )
    async def get_ticket_messages(
        ticket_id: int,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if app_service is None:
            raise SuperOfficeIntegrationError(
                "SuperOffice service is not configured or unavailable.",
                error_code="SUPEROFFICE_SERVICE_UNCONFIGURED",
            )
        msgs = await app_service.get_ticket_messages(ticket_id)
        if limit is not None and limit > 0:
            msgs = msgs[:limit]
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
        category: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if app_service is None:
            raise SuperOfficeIntegrationError(
                "SuperOffice service is not configured or unavailable.",
                error_code="SUPEROFFICE_SERVICE_UNCONFIGURED",
            )
        criteria = CompanySearchCriteriaDTO(name=name, category=category, page_size=limit)
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
        contact_id: int | None = None,
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
            company_id=contact_id,
            page_size=limit,
        )
        res = await app_service.find_persons(criteria)
        return res.model_dump(mode="json")

    active_sync_service = sync_service

    @mcp_server.tool(
        name="sync_codebase",
        description=(
            "Sync SuperOffice CRMScripts, screens, and custom tables to local mirror directory"
        ),
    )
    async def sync_codebase(
        mode: str | None = None,
        tables: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        nonlocal active_sync_service
        if active_sync_service is None:
            active_sync_service = SuperOfficeCodebaseSyncService()
        selected_tables = (
            [t.strip() for t in tables.split(",") if t.strip()] if tables else None
        )
        res = await active_sync_service.sync(mode=mode, tables=selected_tables, dry_run=dry_run)
        return res.model_dump(mode="json")

    return mcp_server


def create_app(
    settings: SuperOfficeServerSettings | None = None,
    service: SuperOfficeApplicationService | None = None,
    client: SuperOfficeClient | None = None,
    sync_service: SuperOfficeCodebaseSyncService | None = None,
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

    server = create_superoffice_mcp_server(service=active_service, sync_service=sync_service)
    return server.streamable_http_app()

