"""SuperOffice MCP Server FastMCP runtime application exposing /mcp tools."""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from so_mcp.adapters.factory import create_superoffice_client
from so_mcp.audit.contracts import TicketAuditCriteriaDTO
from so_mcp.audit.factory import create_ticket_audit_service
from so_mcp.audit.service import TicketAuditService
from so_mcp.codebase.contracts import (
    CodebaseFileRequestDTO,
    CodebaseSearchCriteriaDTO,
)
from so_mcp.codebase.factory import create_codebase_intelligence_service
from so_mcp.codebase.service import CodebaseIntelligenceService
from so_mcp.contracts.dtos import (
    CompanySearchCriteriaDTO,
    PersonSearchCriteriaDTO,
    TicketSearchCriteriaDTO,
)
from so_mcp.contracts.errors import SuperOfficeIntegrationError
from so_mcp.contracts.interfaces import SuperOfficeClient
from so_mcp.extra_tables.contracts import ExtraTableQueryCriteriaDTO
from so_mcp.extra_tables.factory import create_extra_table_service
from so_mcp.extra_tables.service import ExtraTableService
from so_mcp.metadata.contracts import (
    AssociateDetailCriteriaDTO,
    SystemEventsCriteriaDTO,
    TicketMetadataListsCriteriaDTO,
)
from so_mcp.metadata.factory import create_metadata_service
from so_mcp.metadata.service import SuperOfficeMetadataService
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


def create_superoffice_mcp_server(  # noqa: PLR0915, PLR0917
    service: SuperOfficeApplicationService | None = None,
    client: SuperOfficeClient | None = None,
    sync_service: SuperOfficeCodebaseSyncService | None = None,
    extra_table_service: ExtraTableService | None = None,
    audit_service: TicketAuditService | None = None,
    codebase_service: CodebaseIntelligenceService | None = None,
    metadata_service: SuperOfficeMetadataService | None = None,
) -> FastMCP:
    """Instantiate and configure the official FastMCP SuperOffice server.

    Registers approved SuperOffice operations, extra tables tools, and codebase sync tools.
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
        selected_tables = [t.strip() for t in tables.split(",") if t.strip()] if tables else None
        res = await active_sync_service.sync(mode=mode, tables=selected_tables, dry_run=dry_run)
        return res.model_dump(mode="json")

    active_extra_table_service = extra_table_service

    @mcp_server.tool(
        name="list_extra_tables",
        description=(
            "List registered SuperOffice custom extra tables (y_*) with metadata and field counts"
        ),
    )
    async def list_extra_tables(search: str | None = None) -> dict[str, Any]:
        nonlocal active_extra_table_service
        if active_extra_table_service is None:
            active_extra_table_service = create_extra_table_service()
        tables = await active_extra_table_service.list_extra_tables(search=search)
        return {
            "tables": [t.model_dump(mode="json") for t in tables],
            "total_count": len(tables),
        }

    @mcp_server.tool(
        name="get_extra_table_schema",
        description=(
            "Retrieve column definitions, labels, data types, and defaults for a specific y_* table"
        ),
    )
    async def get_extra_table_schema(table_name: str) -> dict[str, Any]:
        nonlocal active_extra_table_service
        if active_extra_table_service is None:
            active_extra_table_service = create_extra_table_service()
        schema = await active_extra_table_service.get_extra_table_schema(table_name=table_name)
        return schema.model_dump(mode="json")

    @mcp_server.tool(
        name="query_extra_table",
        description=(
            "Query records from a specific SuperOffice custom extra table with "
            "column-level filtering, projection, ordering, and pagination"
        ),
    )
    async def query_extra_table(  # noqa: PLR0917
        table_name: str,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        order_by: str | None = "id",
        order_direction: str = "asc",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        nonlocal active_extra_table_service
        if active_extra_table_service is None:
            active_extra_table_service = create_extra_table_service()
        direction = "desc" if order_direction and order_direction.lower() == "desc" else "asc"
        criteria = ExtraTableQueryCriteriaDTO(
            table_name=table_name,
            fields=tuple(fields) if fields else None,
            filters=filters,
            order_by=order_by,
            order_direction=direction,
            limit=limit,
            offset=offset,
        )
        res = await active_extra_table_service.query_extra_table(criteria)
        return res.model_dump(mode="json")

    active_audit_service = audit_service

    @mcp_server.tool(
        name="get_ticket_audit_trail",
        description=(
            "Retrieve the complete, chronological audit trail and change history for a "
            "SuperOffice ticket, including high-level lifecycle events, user actions, and "
            "granular before/after field mutations."
        ),
    )
    async def get_ticket_audit_trail(
        ticket_id: int,
        include_field_changes: bool = True,
        limit: int = 50,
    ) -> dict[str, Any]:
        nonlocal active_audit_service
        if active_audit_service is None:
            active_audit_service = create_ticket_audit_service()
        criteria = TicketAuditCriteriaDTO(
            ticket_id=ticket_id,
            include_field_changes=include_field_changes,
            limit=limit,
        )
        res = await active_audit_service.get_ticket_audit_trail(criteria)
        return res.model_dump(mode="json")

    active_codebase_service = codebase_service

    @mcp_server.tool(
        name="search_codebase",
        description=(
            "Search across all mirrored SuperOffice CRMScripts, screen definitions, button "
            "actions, and element creation scripts by keyword, path, or regex pattern."
        ),
    )
    async def search_codebase(
        query: str,
        target_type: str = "all",
        screen_name: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        nonlocal active_codebase_service
        if active_codebase_service is None:
            active_codebase_service = create_codebase_intelligence_service()
        criteria = CodebaseSearchCriteriaDTO(
            query=query,
            target_type=target_type,  # type: ignore[arg-type]
            screen_name=screen_name,
            limit=limit,
        )
        res = await active_codebase_service.search_codebase(criteria)
        return res.model_dump(mode="json")

    @mcp_server.tool(
        name="get_codebase_file",
        description=(
            "Safely retrieve the content of a mirrored CRMScript or screen definition file "
            "with bounded line windowing and path traversal protection."
        ),
    )
    async def get_codebase_file(
        relative_path: str,
        start_line: int = 1,
        end_line: int = 100,
    ) -> dict[str, Any]:
        nonlocal active_codebase_service
        if active_codebase_service is None:
            active_codebase_service = create_codebase_intelligence_service()
        req = CodebaseFileRequestDTO(
            relative_path=relative_path,
            start_line=start_line,
            end_line=end_line,
        )
        res = await active_codebase_service.get_codebase_file(req)
        return res.model_dump(mode="json")

    @mcp_server.tool(
        name="get_screen_details",
        description=(
            "Inspect the structural layout, constituent elements, button actions, and "
            "associated lifecycle scripts of a SuperOffice screen by name or ID."
        ),
    )
    async def get_screen_details(screen_name_or_id: str) -> dict[str, Any]:
        nonlocal active_codebase_service
        if active_codebase_service is None:
            active_codebase_service = create_codebase_intelligence_service()
        res = await active_codebase_service.get_screen_details(screen_name_or_id)
        if res is None:
            return {
                "error": f"Screen '{screen_name_or_id}' not found in mirrored codebase.",
                "found": False,
            }
        data = res.model_dump(mode="json")
        data["found"] = True
        return data

    active_metadata_service = metadata_service

    @mcp_server.tool(
        name="get_associate_details",
        description=(
            "Retrieve details for an internal SuperOffice consultant, support engineer, "
            "or technician by associate ID or username."
        ),
    )
    async def get_associate_details(
        associate_id: int | None = None,
        username: str | None = None,
    ) -> dict[str, Any]:
        nonlocal active_metadata_service
        if active_metadata_service is None:
            active_metadata_service = create_metadata_service()
        criteria = AssociateDetailCriteriaDTO(associate_id=associate_id, username=username)
        res = await active_metadata_service.get_associate_details(criteria)
        if res is None:
            return {
                "found": False,
                "error": f"Associate not found for id={associate_id}, username={username}",
            }
        data = res.model_dump(mode="json")
        data["found"] = True
        return data

    @mcp_server.tool(
        name="get_ticket_metadata_lists",
        description=(
            "Retrieve system reference lists including ticket categories, priorities, "
            "statuses, and user groups."
        ),
    )
    async def get_ticket_metadata_lists(
        list_type: str = "all",
    ) -> dict[str, Any]:
        nonlocal active_metadata_service
        if active_metadata_service is None:
            active_metadata_service = create_metadata_service()
        criteria = TicketMetadataListsCriteriaDTO(list_type=list_type)  # type: ignore[arg-type]
        res = await active_metadata_service.get_ticket_metadata_lists(criteria)
        return res.model_dump(mode="json")

    @mcp_server.tool(
        name="list_system_events_and_triggers",
        description=(
            "Inspect scheduled background tasks, cron execution statuses, and CRMScript "
            "bindings across the SuperOffice system."
        ),
    )
    async def list_system_events_and_triggers(
        include_disabled: bool = True,
        only_errors: bool = False,
        query: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        nonlocal active_metadata_service
        if active_metadata_service is None:
            active_metadata_service = create_metadata_service()
        criteria = SystemEventsCriteriaDTO(
            include_disabled=include_disabled,
            only_errors=only_errors,
            query=query,
            limit=limit,
        )
        res = await active_metadata_service.list_system_events_and_triggers(criteria)
        return res.model_dump(mode="json")

    return mcp_server


def create_app(  # noqa: PLR0917
    settings: SuperOfficeServerSettings | None = None,
    service: SuperOfficeApplicationService | None = None,
    client: SuperOfficeClient | None = None,
    sync_service: SuperOfficeCodebaseSyncService | None = None,
    extra_table_service: ExtraTableService | None = None,
    audit_service: TicketAuditService | None = None,
    codebase_service: CodebaseIntelligenceService | None = None,
    metadata_service: SuperOfficeMetadataService | None = None,
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

    server = create_superoffice_mcp_server(
        service=active_service,
        sync_service=sync_service,
        extra_table_service=extra_table_service,
        audit_service=audit_service,
        codebase_service=codebase_service,
        metadata_service=metadata_service,
    )
    return server.streamable_http_app()
