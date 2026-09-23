"""SuperOffice REST API and OData Archive integration client adapter."""

import json
from typing import Any

from platform_core.errors import TimeoutError as PlatformTimeoutError
from platform_http.client import HttpClient
from platform_http.models import HttpMethod, HttpRequest, HttpResponse
from platform_security.models import AttachmentMetadata
from so_mcp.adapters.mappers import (
    map_attachment_metadata,
    map_contact_entity,
    map_contact_summary_row,
    map_person_entity,
    map_person_summary_row,
    map_ticket_entity,
    map_ticket_message_row,
    map_ticket_summary_row,
)
from so_mcp.adapters.pagination import (
    deserialize_odata_page,
    escape_archive_string_literal,
    html_to_plain_text,
)
from so_mcp.contracts.dtos import (
    CompanyDomainDTO,
    CompanySearchCriteriaDTO,
    PersonDomainDTO,
    PersonSearchCriteriaDTO,
    SuperOfficePageResponse,
    TicketDetailDomainDTO,
    TicketMessageDomainDTO,
    TicketSearchCriteriaDTO,
    TicketSummaryDomainDTO,
)
from so_mcp.contracts.errors import (
    SuperOfficeAuthenticationError,
    SuperOfficeEntityNotFoundError,
    SuperOfficeIntegrationError,
)
from so_mcp.contracts.interfaces import SuperOfficeClient


class SuperOfficeRestClient(SuperOfficeClient):
    """Concrete SuperOffice integration client implementing SuperOfficeClient Protocol."""

    def __init__(
        self,
        client: HttpClient,
        base_url: str,
        auth_header: str,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._auth_header = auth_header

    def _build_request(
        self,
        endpoint_path: str,
        params: dict[str, str] | None = None,
    ) -> HttpRequest:
        """Construct a strongly-typed HttpRequest with Basic Authentication."""
        url = f"{self._base_url}/{endpoint_path.lstrip('/')}"
        headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json",
        }
        return HttpRequest(
            url=url,
            method=HttpMethod.GET,
            headers=headers,
            params=params or {},
            retry_safe=True,
        )

    async def _execute_request(
        self,
        request: HttpRequest,
        operation: str,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
    ) -> HttpResponse:
        """Execute request through resilient HTTP client and apply deterministic error mapping."""
        try:
            response = await self._client.send(request)
        except PlatformTimeoutError:
            raise SuperOfficeIntegrationError(
                message=f"SuperOffice request timed out during {operation}.",
                error_code="SUPEROFFICE_TIMEOUT",
                details={"operation": operation, "status_code": 408},
            ) from None
        except Exception:
            raise SuperOfficeIntegrationError(
                message=f"Failed to connect to SuperOffice during {operation}.",
                error_code="SUPEROFFICE_CONNECTION_FAILURE",
                details={"operation": operation},
            ) from None

        status = response.status_code
        if 200 <= status < 300:
            return response

        if status == 401:
            raise SuperOfficeAuthenticationError(
                message="SuperOffice API authentication failed.",
                details={"operation": operation, "status_code": 401},
            )
        if status == 403:
            raise SuperOfficeIntegrationError(
                message="SuperOffice API access forbidden.",
                error_code="SUPEROFFICE_ACCESS_DENIED",
                details={"operation": operation, "status_code": 403},
            )
        if status == 404:
            e_type = entity_type or "Entity"
            e_id = entity_id if entity_id is not None else "unknown"
            raise SuperOfficeEntityNotFoundError(entity_type=e_type, identifier=e_id)
        if status == 429:
            raise SuperOfficeIntegrationError(
                message=f"SuperOffice rate limit exceeded during {operation}.",
                error_code="SUPEROFFICE_RATE_LIMITED",
                details={"operation": operation, "status_code": 429},
            )
        if status in (500, 502, 503, 504):
            raise SuperOfficeIntegrationError(
                message=f"SuperOffice upstream server error ({status}) during {operation}.",
                error_code="SUPEROFFICE_SERVER_ERROR",
                details={"operation": operation, "status_code": status},
            )

        raise SuperOfficeIntegrationError(
            message=f"SuperOffice request failed with status {status} during {operation}.",
            details={"operation": operation, "status_code": status},
        )

    def _parse_json(self, response: HttpResponse, operation: str) -> Any:
        """Safely parse JSON response body."""
        try:
            return json.loads(response.body_text)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise SuperOfficeIntegrationError(
                message=f"Malformed response payload received during {operation}.",
                error_code="SUPEROFFICE_MALFORMED_RESPONSE",
                details={"operation": operation},
            ) from None

    async def get_ticket(self, ticket_id: int) -> TicketDetailDomainDTO:
        """Retrieve full details of a specific ticket, fetching opening message for description."""
        req = self._build_request(f"/api/v1/Ticket/{ticket_id}")
        resp = await self._execute_request(req, "get_ticket", "Ticket", ticket_id)
        raw_ticket = self._parse_json(resp, "get_ticket")

        if not isinstance(raw_ticket, dict):
            raise SuperOfficeIntegrationError(
                message="Malformed ticket payload received from SuperOffice API.",
                error_code="SUPEROFFICE_MALFORMED_RESPONSE",
                details={"operation": "get_ticket"},
            )

        # Deterministic opening message retrieval (oldest message first)
        msg_req = self._build_request(
            f"/api/v1/Ticket/{ticket_id}/Messages",
            params={
                "$select": "ticketMessageId,body,htmlBody",
                "$orderby": "createdAt,ticketMessageId",
                "$top": "1",
            },
        )
        msg_resp = await self._execute_request(
            msg_req, "get_ticket_opening_message", "Ticket", ticket_id
        )
        raw_msg_data = self._parse_json(msg_resp, "get_ticket_opening_message")

        description = ""
        if isinstance(raw_msg_data, dict):
            items = raw_msg_data.get("value")
            if isinstance(items, list) and items:
                first_item = items[0]
                if isinstance(first_item, dict):
                    raw_body = first_item.get("body") or ""
                    if not raw_body:
                        raw_html = first_item.get("htmlBody") or ""
                        description = html_to_plain_text(str(raw_html))
                    else:
                        description = str(raw_body).strip()
        elif isinstance(raw_msg_data, list) and raw_msg_data:
            first_item = raw_msg_data[0]
            if isinstance(first_item, dict):
                raw_body = first_item.get("body") or ""
                if not raw_body:
                    raw_html = first_item.get("htmlBody") or ""
                    description = html_to_plain_text(str(raw_html))
                else:
                    description = str(raw_body).strip()

        return map_ticket_entity(raw_ticket, description=description)

    async def search_tickets(
        self, criteria: TicketSearchCriteriaDTO
    ) -> SuperOfficePageResponse[TicketSummaryDomainDTO]:
        """Search tickets using SuperOffice Ticket archive provider with fixed projection."""
        select_fields = (
            "ticketId,title,ticketStatusName,categoryFullName,priorityName,createdAt,lastChanged"
        )
        params: dict[str, str] = {
            "$select": select_fields,
            "$top": str(criteria.page_size),
            "$skip": str((criteria.page - 1) * criteria.page_size),
        }

        filters: list[str] = []
        if criteria.title:
            escaped_title = escape_archive_string_literal(criteria.title)
            filters.append(f"title contains '{escaped_title}'")
        if criteria.category:
            escaped_category = escape_archive_string_literal(criteria.category)
            filters.append(f"category/name = '{escaped_category}'")
        if criteria.status:
            escaped_status = escape_archive_string_literal(criteria.status)
            filters.append(f"ticketStatus/name = '{escaped_status}'")
        if criteria.category_id is not None:
            filters.append(f"categoryId = {criteria.category_id}")
        if criteria.customer_id is not None:
            filters.append(f"contactId = {criteria.customer_id}")

        if filters:
            params["$filter"] = " and ".join(filters)

        req = self._build_request("/api/v1/Ticket", params=params)
        resp = await self._execute_request(req, "search_tickets")
        raw_data = self._parse_json(resp, "search_tickets")

        return deserialize_odata_page(
            raw_data, map_ticket_summary_row, criteria.page, criteria.page_size
        )

    async def get_company(self, company_id: int) -> CompanyDomainDTO:
        """Retrieve full company details via SuperOffice ContactEntity endpoint."""
        req = self._build_request(f"/api/v1/Contact/{company_id}")
        resp = await self._execute_request(req, "get_company", "Company", company_id)
        raw_data = self._parse_json(resp, "get_company")

        if not isinstance(raw_data, dict):
            raise SuperOfficeIntegrationError(
                message="Malformed company payload received from SuperOffice API.",
                error_code="SUPEROFFICE_MALFORMED_RESPONSE",
                details={"operation": "get_company"},
            )

        return map_contact_entity(raw_data)

    async def find_companies(
        self, criteria: CompanySearchCriteriaDTO
    ) -> SuperOfficePageResponse[CompanyDomainDTO]:
        """Search companies using SuperOffice Contact archive provider."""
        params: dict[str, str] = {
            "$select": "contactId,name,department,orgnr",
            "$top": str(criteria.page_size),
            "$skip": str((criteria.page - 1) * criteria.page_size),
        }

        filters: list[str] = []
        if criteria.name:
            escaped_name = escape_archive_string_literal(criteria.name)
            filters.append(f"name contains '{escaped_name}'")
        if criteria.category:
            escaped_category = escape_archive_string_literal(criteria.category)
            filters.append(f"category/name = '{escaped_category}'")
        if criteria.company_id is not None:
            filters.append(f"contactId = {criteria.company_id}")

        if filters:
            params["$filter"] = " and ".join(filters)

        req = self._build_request("/api/v1/Contact", params=params)
        resp = await self._execute_request(req, "find_companies")
        raw_data = self._parse_json(resp, "find_companies")

        return deserialize_odata_page(
            raw_data, map_contact_summary_row, criteria.page, criteria.page_size
        )

    async def get_person(self, person_id: int) -> PersonDomainDTO:
        """Retrieve individual contact/person details via SuperOffice PersonEntity endpoint."""
        req = self._build_request(f"/api/v1/Person/{person_id}")
        resp = await self._execute_request(req, "get_person", "Person", person_id)
        raw_data = self._parse_json(resp, "get_person")

        if not isinstance(raw_data, dict):
            raise SuperOfficeIntegrationError(
                message="Malformed person payload received from SuperOffice API.",
                error_code="SUPEROFFICE_MALFORMED_RESPONSE",
                details={"operation": "get_person"},
            )

        return map_person_entity(raw_data)

    async def find_persons(
        self, criteria: PersonSearchCriteriaDTO
    ) -> SuperOfficePageResponse[PersonDomainDTO]:
        """Search persons using SuperOffice Person archive provider."""
        select_fields = (
            "personId,firstName,lastName,contactId,email/emailAddress,"
            "personDirectPhone/formattedNumber"
        )
        params: dict[str, str] = {
            "$select": select_fields,
            "$top": str(criteria.page_size),
            "$skip": str((criteria.page - 1) * criteria.page_size),
        }

        filters: list[str] = []
        if criteria.name:
            escaped_name = escape_archive_string_literal(criteria.name)
            filters.append(
                f"(firstName contains '{escaped_name}' or lastName contains '{escaped_name}')"
            )
        if criteria.email:
            escaped_email = escape_archive_string_literal(criteria.email)
            filters.append(f"email/emailAddress = '{escaped_email}'")
        if criteria.company_id is not None:
            filters.append(f"contactId = {criteria.company_id}")

        if filters:
            params["$filter"] = " and ".join(filters)

        req = self._build_request("/api/v1/Person", params=params)
        resp = await self._execute_request(req, "find_persons")
        raw_data = self._parse_json(resp, "find_persons")

        return deserialize_odata_page(
            raw_data, map_person_summary_row, criteria.page, criteria.page_size
        )

    async def get_ticket_messages(self, ticket_id: int) -> list[TicketMessageDomainDTO]:
        """Retrieve message history for a ticket via TicketMessage archive endpoint."""
        params: dict[str, str] = {
            "$select": "ticketMessageId,ticketId,author,createdAt,body,htmlBody",
        }
        req = self._build_request(f"/api/v1/Ticket/{ticket_id}/Messages", params=params)
        resp = await self._execute_request(req, "get_ticket_messages", "Ticket", ticket_id)
        raw_data = self._parse_json(resp, "get_ticket_messages")

        items: list[Any] = []
        if isinstance(raw_data, dict):
            raw_items = raw_data.get("value")
            if isinstance(raw_items, list):
                items = raw_items
        elif isinstance(raw_data, list):
            items = raw_data

        return [
            map_ticket_message_row(item, default_ticket_id=ticket_id)
            for item in items
            if isinstance(item, dict)
        ]

    async def list_attachments(self, ticket_id: int) -> list[AttachmentMetadata]:
        """List metadata of attachments associated with a ticket (no binary downloads)."""
        req = self._build_request(f"/api/v1/Ticket/{ticket_id}/Attachments")
        resp = await self._execute_request(req, "list_attachments", "Ticket", ticket_id)
        raw_data = self._parse_json(resp, "list_attachments")

        items: list[Any] = []
        if isinstance(raw_data, dict):
            raw_items = raw_data.get("value")
            if isinstance(raw_items, list):
                items = raw_items
        elif isinstance(raw_data, list):
            items = raw_data

        return [map_attachment_metadata(item) for item in items if isinstance(item, dict)]
