"""Offline unit tests for SuperOfficeRestClient using respx."""

import httpx
import pytest
import respx
from pydantic import HttpUrl, SecretStr

from so_mcp.adapters.factory import create_superoffice_client
from so_mcp.adapters.rest_client import SuperOfficeRestClient
from so_mcp.contracts.dtos import (
    CompanySearchCriteriaDTO,
    PersonSearchCriteriaDTO,
    TicketSearchCriteriaDTO,
)
from so_mcp.contracts.errors import (
    SuperOfficeAuthenticationError,
    SuperOfficeEntityNotFoundError,
    SuperOfficeIntegrationError,
)
from so_mcp.settings import SuperOfficeServerSettings


@pytest.fixture
def test_settings() -> SuperOfficeServerSettings:
    """Fixture providing test SuperOfficeServerSettings."""
    return SuperOfficeServerSettings(
        api_url=HttpUrl("https://crm.test.local/SuperOffice"),
        username="test_api_user",
        password=SecretStr("test_api_password_123"),
        timeout_seconds=5,
        allow_self_signed_cert=False,
    )


@pytest.fixture
def rest_client(test_settings: SuperOfficeServerSettings) -> SuperOfficeRestClient:
    """Fixture providing an instantiated SuperOfficeRestClient."""
    client = create_superoffice_client(test_settings)
    assert isinstance(client, SuperOfficeRestClient)
    return client


@respx.mock
async def test_get_ticket_success_with_opening_message(rest_client: SuperOfficeRestClient) -> None:
    """Test get_ticket successfully fetches TicketEntity and opening message description."""
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/101").respond(
        status_code=200,
        json={
            "TicketId": 101,
            "Title": "Cannot connect to database",
            "Status": {"Name": "Open"},
            "Category": {"Name": "Database"},
            "Priority": {"Name": "High"},
            "AssignedTo": {"FullName": "Agent John"},
            "CustId": 501,
            "TicketUrl": "TICK-101",
            "CreatedAt": "2026-08-20T10:00:00Z",
            "LastModified": "2026-08-20T11:00:00Z",
        },
    )
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/101/Messages").respond(
        status_code=200,
        json={
            "value": [
                {
                    "ticketMessageId": 1,
                    "ticketId": 101,
                    "author": "Customer Alice",
                    "body": "Database connection times out when running report.",
                    "createdAt": "2026-08-20T10:01:00Z",
                }
            ]
        },
    )

    ticket = await rest_client.get_ticket(101)
    assert ticket.ticket_id == 101
    assert ticket.title == "Cannot connect to database"
    assert ticket.status == "Open"
    assert ticket.category == "Database"
    assert ticket.priority == "High"
    assert ticket.description == "Database connection times out when running report."
    assert ticket.assigned_to == "Agent John"
    assert ticket.customer_id == 501


@respx.mock
async def test_get_ticket_zero_messages_sets_empty_description(
    rest_client: SuperOfficeRestClient,
) -> None:
    """Test get_ticket when ticket has zero messages sets description to empty string."""
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/102").respond(
        status_code=200,
        json={
            "TicketId": 102,
            "Title": "New inquiry",
            "Status": "New",
            "Category": "Support",
            "Priority": "Low",
            "CreatedAt": "2026-08-20T12:00:00Z",
            "LastModified": "2026-08-20T12:00:00Z",
        },
    )
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/102/Messages").respond(
        status_code=200,
        json={"value": []},
    )

    ticket = await rest_client.get_ticket(102)
    assert ticket.ticket_id == 102
    assert ticket.description == ""


@respx.mock
async def test_get_ticket_opening_message_failure_propagates_error(
    rest_client: SuperOfficeRestClient,
) -> None:
    """Test get_ticket propagates typed integration error when opening message request fails."""
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/103").respond(
        status_code=200,
        json={
            "TicketId": 103,
            "Title": "Broken hardware",
            "Status": "Open",
            "Category": "Hardware",
            "Priority": "High",
            "CreatedAt": "2026-08-20T12:00:00Z",
            "LastModified": "2026-08-20T12:00:00Z",
        },
    )
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/103/Messages").respond(
        status_code=500,
    )

    with pytest.raises(SuperOfficeIntegrationError) as exc_info:
        await rest_client.get_ticket(103)
    assert exc_info.value.error_code == "SUPEROFFICE_SERVER_ERROR"


@respx.mock
async def test_get_ticket_not_found(rest_client: SuperOfficeRestClient) -> None:
    """Test get_ticket 404 maps to SuperOfficeEntityNotFoundError."""
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/999").respond(status_code=404)

    with pytest.raises(SuperOfficeEntityNotFoundError) as exc_info:
        await rest_client.get_ticket(999)
    assert "SuperOffice Ticket" in str(exc_info.value)
    assert "999" in str(exc_info.value)


@respx.mock
async def test_search_tickets_query_and_filter_building(
    rest_client: SuperOfficeRestClient,
) -> None:
    """Test search_tickets with status, category, and customer criteria."""
    route = respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket").respond(
        status_code=200,
        json={
            "odata.nextLink": "https://crm.test.local/SuperOffice/api/v1/Ticket?$skip=10",
            "value": [
                {
                    "ticketId": 101,
                    "title": "DB Timeout",
                    "ticketStatusName": "Open",
                    "categoryFullName": "Database",
                    "priorityName": "High",
                    "createdAt": "2026-08-20T10:00:00Z",
                    "lastChanged": "2026-08-20T11:00:00Z",
                }
            ],
        },
    )

    criteria = TicketSearchCriteriaDTO(
        status="Open",
        category_id=2,
        customer_id=501,
        page=2,
        page_size=10,
    )
    result = await rest_client.search_tickets(criteria)

    assert route.called
    req = route.calls.last.request
    assert req.url.params["$top"] == "10"
    assert req.url.params["$skip"] == "10"
    assert req.url.params["$select"] == (
        "ticketId,title,ticketStatusName,categoryFullName,priorityName,createdAt,lastChanged"
    )
    assert req.url.params["$filter"] == (
        "ticketStatus/name = 'Open' and categoryId = 2 and contactId = 501"
    )

    assert len(result.items) == 1
    assert result.page == 2
    assert result.page_size == 10
    assert result.has_next_page is True


@respx.mock
async def test_company_endpoints(rest_client: SuperOfficeRestClient) -> None:
    """Test get_company and find_companies endpoints."""
    respx.get("https://crm.test.local/SuperOffice/api/v1/Contact/501").respond(
        status_code=200,
        json={
            "ContactId": 501,
            "Name": "Nordic Solutions AS",
            "Department": "Oslo",
            "OrgNr": "NO-123456789",
        },
    )
    search_route = respx.get("https://crm.test.local/SuperOffice/api/v1/Contact").respond(
        status_code=200,
        json={
            "value": [
                {
                    "contactId": 501,
                    "name": "Nordic Solutions AS",
                    "department": "Oslo",
                    "orgnr": "NO-123456789",
                }
            ]
        },
    )

    company = await rest_client.get_company(501)
    assert company.company_id == 501
    assert company.name == "Nordic Solutions AS"

    search_page = await rest_client.find_companies(
        CompanySearchCriteriaDTO(name="Nordic", company_id=501, page=1, page_size=20)
    )
    assert search_route.called
    req = search_route.calls.last.request
    assert req.url.params["$select"] == "contactId,name,department,orgnr"
    assert req.url.params["$filter"] == "name contains 'Nordic' and contactId = 501"
    assert len(search_page.items) == 1


@respx.mock
async def test_person_endpoints(rest_client: SuperOfficeRestClient) -> None:
    """Test get_person and find_persons endpoints."""
    respx.get("https://crm.test.local/SuperOffice/api/v1/Person/801").respond(
        status_code=200,
        json={
            "PersonId": 801,
            "Firstname": "Astrid",
            "Lastname": "Lindgren",
            "Email": "astrid@example.com",
            "Phone": "+46 8123456",
            "ContactId": 501,
        },
    )
    search_route = respx.get("https://crm.test.local/SuperOffice/api/v1/Person").respond(
        status_code=200,
        json={
            "value": [
                {
                    "personId": 801,
                    "firstName": "Astrid",
                    "lastName": "Lindgren",
                    "email/emailAddress": "astrid@example.com",
                    "personDirectPhone/formattedNumber": "+46 8123456",
                    "contactId": 501,
                }
            ]
        },
    )

    person = await rest_client.get_person(801)
    assert person.person_id == 801
    assert person.first_name == "Astrid"

    search_page = await rest_client.find_persons(
        PersonSearchCriteriaDTO(
            name="Astrid",
            email="astrid@example.com",
            company_id=501,
            page=1,
            page_size=20,
        )
    )
    assert search_route.called
    req = search_route.calls.last.request
    assert req.url.params["$select"] == (
        "personId,firstName,lastName,contactId,email/emailAddress,personDirectPhone/formattedNumber"
    )
    assert req.url.params["$filter"] == (
        "(firstName contains 'Astrid' or lastName contains 'Astrid') and "
        "email/emailAddress = 'astrid@example.com' and contactId = 501"
    )
    assert len(search_page.items) == 1


@respx.mock
async def test_get_ticket_messages_and_list_attachments(
    rest_client: SuperOfficeRestClient,
) -> None:
    """Test get_ticket_messages and list_attachments endpoints."""
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/101/Messages").respond(
        status_code=200,
        json={
            "value": [
                {
                    "ticketMessageId": 10,
                    "ticketId": 101,
                    "author": "Support Admin",
                    "body": "Rebooting the server now.",
                    "createdAt": "2026-08-20T10:15:00Z",
                }
            ]
        },
    )
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/101/Attachments").respond(
        status_code=200,
        json={
            "value": [
                {
                    "AttachmentId": 99,
                    "Name": "log_dump.txt",
                    "ContentType": "text/plain",
                    "AttSize": 1024,
                }
            ]
        },
    )

    messages = await rest_client.get_ticket_messages(101)
    assert len(messages) == 1
    assert messages[0].message_id == 10
    assert messages[0].body == "Rebooting the server now."

    attachments = await rest_client.list_attachments(101)
    assert len(attachments) == 1
    assert attachments[0].attachment_id == 99
    assert attachments[0].filename == "log_dump.txt"
    assert attachments[0].mime_type == "text/plain"
    assert attachments[0].size_bytes == 1024


@respx.mock
async def test_authentication_and_authorization_errors(
    rest_client: SuperOfficeRestClient,
) -> None:
    """Test HTTP 401 and 403 error mapping."""
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/401").respond(status_code=401)
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/403").respond(status_code=403)

    with pytest.raises(SuperOfficeAuthenticationError) as auth_err:
        await rest_client.get_ticket(401)
    assert auth_err.value.error_code == "SUPEROFFICE_AUTH_FAILURE"

    with pytest.raises(SuperOfficeIntegrationError) as int_err:
        await rest_client.get_ticket(403)
    assert int_err.value.error_code == "SUPEROFFICE_ACCESS_DENIED"


@respx.mock
async def test_rate_limit_and_server_errors(rest_client: SuperOfficeRestClient) -> None:
    """Test HTTP 429 and 500 error mapping."""
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/429").respond(status_code=429)
    respx.get("https://crm.test.local/SuperOffice/api/v1/Ticket/500").respond(status_code=500)

    with pytest.raises(SuperOfficeIntegrationError) as rate_err:
        await rest_client.get_ticket(429)
    assert rate_err.value.error_code == "SUPEROFFICE_RATE_LIMITED"

    with pytest.raises(SuperOfficeIntegrationError) as srv_err:
        await rest_client.get_ticket(500)
    assert srv_err.value.error_code == "SUPEROFFICE_SERVER_ERROR"


@respx.mock
async def test_transient_503_retry_success(rest_client: SuperOfficeRestClient) -> None:
    """Test that a transient 503 error is retried and succeeds."""
    route = respx.get("https://crm.test.local/SuperOffice/api/v1/Contact/502")
    route.side_effect = [
        httpx.Response(status_code=503),
        httpx.Response(
            status_code=200,
            json={"ContactId": 502, "Name": "Retried Enterprise"},
        ),
    ]

    company = await rest_client.get_company(502)
    assert company.company_id == 502
    assert company.name == "Retried Enterprise"
    assert route.call_count == 2
