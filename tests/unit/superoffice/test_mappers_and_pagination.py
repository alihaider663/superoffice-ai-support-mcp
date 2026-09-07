"""Unit tests for SuperOffice response mappers, OData pagination, and archive string escaping."""

from datetime import UTC, datetime

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


def test_escape_archive_string_literal_handles_apostrophes_and_backslashes() -> None:
    """Test that archive string escaping safely escapes apostrophes and backslashes."""
    assert escape_archive_string_literal("O'Connor") == r"O\'Connor"
    assert escape_archive_string_literal(r"C:\Support\Log") == r"C:\\Support\\Log"
    assert escape_archive_string_literal("' or 1 eq 1") == r"\' or 1 eq 1"
    assert (
        escape_archive_string_literal("') or getAllRows = true or ('")
        == r"\') or getAllRows = true or (\'"
    )


def test_html_to_plain_text_strips_tags_and_unescapes_entities() -> None:
    """Test converting HTML content into normalized plain text."""
    html_input = (
        "<p>Hello <b>World</b>!</p><br/><div>Issue details &amp; logs: critical_error</div>"
    )
    plain = html_to_plain_text(html_input)
    assert "Hello World!" in plain
    assert "Issue details & logs: critical_error" in plain
    assert "<p>" not in plain
    assert "<div>" not in plain


def test_map_ticket_entity_full_pascal_case() -> None:
    """Test mapping a full SuperOffice TicketEntity JSON dictionary."""
    raw = {
        "TicketId": 105,
        "Title": "Network Connection Timeout",
        "Status": {"Name": "Open", "Id": 1},
        "Category": {"Name": "IT / Network", "Id": 2},
        "Priority": {"Name": "High", "Id": 3},
        "AssignedTo": {"FullName": "Tech Support Agent", "Id": 42},
        "CustId": 5001,
        "TicketUrl": "SO-TICK-105",
        "CreatedAt": "2026-08-20T10:00:00Z",
        "LastModified": "2026-08-20T12:00:00Z",
    }
    dto = map_ticket_entity(raw, description="Initial problem description")
    assert dto.ticket_id == 105
    assert dto.title == "Network Connection Timeout"
    assert dto.status == "Open"
    assert dto.category == "IT / Network"
    assert dto.priority == "High"
    assert dto.description == "Initial problem description"
    assert dto.assigned_to == "Tech Support Agent"
    assert dto.customer_id == 5001
    assert dto.customer_reference == "SO-TICK-105"
    assert dto.created_at == datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)
    assert dto.updated_at == datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)


def test_map_ticket_summary_row_archive_columns() -> None:
    """Test mapping an OData archive Ticket row."""
    raw = {
        "ticketId": 201,
        "title": "Email server sync failure",
        "ticketStatusName": "Pending",
        "categoryFullName": "Email",
        "priorityName": "Medium",
        "createdAt": "2026-08-21T08:30:00Z",
        "lastChanged": "2026-08-21T09:00:00Z",
    }
    dto = map_ticket_summary_row(raw)
    assert dto.ticket_id == 201
    assert dto.title == "Email server sync failure"
    assert dto.status == "Pending"
    assert dto.category == "Email"
    assert dto.priority == "Medium"
    assert dto.created_at == datetime(2026, 8, 21, 8, 30, 0, tzinfo=UTC)
    assert dto.updated_at == datetime(2026, 8, 21, 9, 0, 0, tzinfo=UTC)


def test_map_contact_entity_and_summary_row() -> None:
    """Test mapping Contact entity and archive row to CompanyDomainDTO."""
    raw = {
        "ContactId": 401,
        "Name": "Acme Corp",
        "Department": "HQ",
        "OrgNr": "NO-987654321",
    }
    dto1 = map_contact_entity(raw)
    dto2 = map_contact_summary_row(raw)
    for dto in (dto1, dto2):
        assert dto.company_id == 401
        assert dto.name == "Acme Corp"
        assert dto.department == "HQ"
        assert dto.org_number == "NO-987654321"


def test_map_person_entity_and_archive_row() -> None:
    """Test mapping Person entity and archive row with explicit archive columns."""
    raw = {
        "personId": 801,
        "firstName": "Alice",
        "lastName": "Smith",
        "email/emailAddress": "alice.smith@acme.example.com",
        "personDirectPhone/formattedNumber": "+47 12345678",
        "contactId": 401,
    }
    dto = map_person_summary_row(raw)
    assert dto.person_id == 801
    assert dto.first_name == "Alice"
    assert dto.last_name == "Smith"
    assert dto.email == "alice.smith@acme.example.com"
    assert dto.phone == "+47 12345678"
    assert dto.company_id == 401


def test_map_person_entity_fallback_arrays() -> None:
    """Test mapping Person entity with Emails and Phones arrays."""
    raw = {
        "PersonId": 802,
        "Firstname": "Bob",
        "Lastname": "Jones",
        "Emails": [{"Value": "bob@example.com"}],
        "Phones": [{"Value": "+47 99999999"}],
        "ContactId": 402,
    }
    dto = map_person_entity(raw)
    assert dto.person_id == 802
    assert dto.first_name == "Bob"
    assert dto.last_name == "Jones"
    assert dto.email == "bob@example.com"
    assert dto.phone == "+47 99999999"
    assert dto.company_id == 402


def test_map_ticket_message_row_and_html_fallback() -> None:
    """Test mapping TicketMessage archive row with HTML body fallback."""
    raw = {
        "ticketMessageId": 9001,
        "ticketId": 105,
        "author": "Customer Service",
        "htmlBody": "<p>Thank you for reporting. <b>Investigation underway.</b></p>",
        "createdAt": "2026-08-20T10:05:00Z",
    }
    dto = map_ticket_message_row(raw)
    assert dto.message_id == 9001
    assert dto.ticket_id == 105
    assert dto.author == "Customer Service"
    assert dto.author_type == "CUSTOMER"  # Preserves default
    assert "Thank you for reporting. Investigation underway." in dto.body
    assert dto.attachments == ()


def test_map_attachment_metadata_and_auth_key_dropping() -> None:
    """Security Invariant Test: Verify AuthKey and other unapproved fields are stripped."""
    raw = {
        "AttachmentId": 55,
        "Name": "error_screenshot.png",
        "ContentType": "image/png",
        "AttSize": 204800,
        "AuthKey": "SUPER_SECRET_ATTACHMENT_AUTH_TOKEN_XYZ",
        "InlineImage": True,
        "ContentId": "<cid:12345>",
        "TableRight": {"CanRead": True},
        "FieldProperties": {"Hidden": False},
    }
    dto = map_attachment_metadata(raw)
    assert dto.attachment_id == 55
    assert dto.filename == "error_screenshot.png"
    assert dto.mime_type == "image/png"
    assert dto.size_bytes == 204800
    assert dto.md5_hash == ""
    assert dto.is_content_authorized is False

    # Assert AuthKey is NOT present anywhere in model dict or JSON dump
    dto_dict = dto.model_dump()
    assert "AuthKey" not in dto_dict
    assert "SUPER_SECRET_ATTACHMENT_AUTH_TOKEN_XYZ" not in str(dto_dict)
    assert "SUPER_SECRET_ATTACHMENT_AUTH_TOKEN_XYZ" not in dto.model_dump_json()


def test_deserialize_odata_page_pagination_semantics() -> None:
    """Test OData pagination deserialization without guessing total items or false positives."""
    raw_page_1 = {
        "odata.metadata": "https://crm.example.com/api/v1/Ticket",
        "odata.nextLink": "https://crm.example.com/api/v1/Ticket?$skip=2&$top=2",
        "value": [
            {"ticketId": 1, "title": "T1"},
            {"ticketId": 2, "title": "T2"},
        ],
    }
    page_1 = deserialize_odata_page(
        raw_page_1,
        map_ticket_summary_row,
        page=1,
        page_size=2,
    )
    assert len(page_1.items) == 2
    assert page_1.page == 1
    assert page_1.page_size == 2
    assert page_1.total_items is None
    assert page_1.has_next_page is True

    # Page 2: Exactly page_size items, but NO odata.nextLink (final page)
    raw_page_2 = {
        "odata.metadata": "https://crm.example.com/api/v1/Ticket",
        "value": [
            {"ticketId": 3, "title": "T3"},
            {"ticketId": 4, "title": "T4"},
        ],
    }
    page_2 = deserialize_odata_page(
        raw_page_2,
        map_ticket_summary_row,
        page=2,
        page_size=2,
    )
    assert len(page_2.items) == 2
    assert page_2.has_next_page is False  # Must be False because nextLink is absent
