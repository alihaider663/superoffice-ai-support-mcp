"""SuperOffice REST API and OData archive response mappers into Internal Domain DTOs."""

from datetime import UTC, datetime
from typing import Any

from platform_security.models import AttachmentMetadata
from so_mcp.adapters.pagination import html_to_plain_text
from so_mcp.contracts.dtos import (
    CompanyDomainDTO,
    PersonDomainDTO,
    TicketDetailDomainDTO,
    TicketMessageDomainDTO,
    TicketSummaryDomainDTO,
)


def _parse_datetime(value: Any) -> datetime:
    """Parse an ISO 8601 string or return current UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            cleaned = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def map_ticket_entity(raw: dict[str, Any], description: str = "") -> TicketDetailDomainDTO:
    """Map a full SuperOffice TicketEntity JSON response to TicketDetailDomainDTO."""
    ticket_id = int(raw.get("TicketId") or raw.get("ticketId") or 0)
    title = str(raw.get("Title") or raw.get("title") or "")

    # Status handling (can be string or nested dict {"Name": "Open"})
    raw_status = raw.get("Status") or raw.get("status") or raw.get("ticketStatusName") or "Open"
    status_str = (
        str(raw_status.get("Name") or "Open") if isinstance(raw_status, dict) else str(raw_status)
    )

    # Category handling
    raw_cat = raw.get("Category") or raw.get("category") or raw.get("categoryFullName") or "General"
    cat_str = str(raw_cat.get("Name") or "General") if isinstance(raw_cat, dict) else str(raw_cat)

    # Priority handling
    raw_prio = raw.get("Priority") or raw.get("priority") or raw.get("priorityName") or "Medium"
    prio_str = (
        str(raw_prio.get("Name") or "Medium") if isinstance(raw_prio, dict) else str(raw_prio)
    )

    # Assigned agent
    raw_assigned = raw.get("AssignedTo") or raw.get("assignedTo")
    assigned_to = (
        raw_assigned.get("FullName") or str(raw_assigned.get("Id"))
        if isinstance(raw_assigned, dict)
        else (str(raw_assigned) if raw_assigned is not None else None)
    )

    # Customer identifier
    raw_cust = (
        raw.get("CustId")
        or raw.get("custId")
        or (
            raw.get("Person", {}).get("Contact", {}).get("ContactId")
            if isinstance(raw.get("Person"), dict)
            else None
        )
    )
    customer_id = int(raw_cust) if raw_cust is not None else None

    customer_ref = raw.get("TicketUrl") or raw.get("ticketUrl") or raw.get("ExternalRef")
    customer_reference = str(customer_ref) if customer_ref is not None else None

    created_at = _parse_datetime(raw.get("CreatedAt") or raw.get("createdAt"))
    updated_at = _parse_datetime(
        raw.get("LastModified") or raw.get("lastModified") or raw.get("lastChanged")
    )

    return TicketDetailDomainDTO(
        ticket_id=ticket_id,
        title=title,
        status=status_str,
        category=cat_str,
        priority=prio_str,
        description=description,
        assigned_to=assigned_to,
        customer_id=customer_id,
        customer_reference=customer_reference,
        created_at=created_at,
        updated_at=updated_at,
    )


def map_ticket_summary_row(raw: dict[str, Any]) -> TicketSummaryDomainDTO:
    """Map a SuperOffice Ticket archive collection row to TicketSummaryDomainDTO."""
    ticket_id = int(raw.get("ticketId") or raw.get("TicketId") or 0)
    title = str(raw.get("title") or raw.get("Title") or "")
    status = str(raw.get("ticketStatusName") or raw.get("status") or "Open")
    category = str(raw.get("categoryFullName") or raw.get("category") or "General")
    priority = str(raw.get("priorityName") or raw.get("priority") or "Medium")
    created_at = _parse_datetime(raw.get("createdAt") or raw.get("CreatedAt"))
    updated_at = _parse_datetime(
        raw.get("lastChanged") or raw.get("LastModified") or raw.get("updatedAt")
    )

    return TicketSummaryDomainDTO(
        ticket_id=ticket_id,
        title=title,
        status=status,
        category=category,
        priority=priority,
        created_at=created_at,
        updated_at=updated_at,
    )


def map_contact_entity(raw: dict[str, Any]) -> CompanyDomainDTO:
    """Map a SuperOffice ContactEntity JSON response or archive row to CompanyDomainDTO."""
    company_id = int(raw.get("ContactId") or raw.get("contactId") or 0)
    name = str(raw.get("Name") or raw.get("name") or "")
    department = raw.get("Department") or raw.get("department")
    org_number = raw.get("OrgNr") or raw.get("orgnr") or raw.get("OrgNumber")

    return CompanyDomainDTO(
        company_id=company_id,
        name=name,
        department=str(department) if department is not None else None,
        org_number=str(org_number) if org_number is not None else None,
    )


def map_contact_summary_row(raw: dict[str, Any]) -> CompanyDomainDTO:
    """Map a SuperOffice Contact archive row to CompanyDomainDTO."""
    return map_contact_entity(raw)


def map_person_entity(raw: dict[str, Any]) -> PersonDomainDTO:
    """Map a SuperOffice PersonEntity JSON response or archive row to PersonDomainDTO."""
    person_id = int(raw.get("PersonId") or raw.get("personId") or 0)
    first_name = str(raw.get("Firstname") or raw.get("firstName") or "")
    last_name = str(raw.get("Lastname") or raw.get("lastName") or "")

    # Extract email from single field or emails array
    email_val = (
        raw.get("email/emailAddress")
        or raw.get("emailAddress")
        or raw.get("Email")
        or raw.get("email")
    )
    if not email_val and isinstance(raw.get("Emails"), list) and raw["Emails"]:
        first_email = raw["Emails"][0]
        email_val = first_email.get("Value") if isinstance(first_email, dict) else first_email

    # Extract phone from single field or phones array
    phone_val = (
        raw.get("personDirectPhone/formattedNumber")
        or raw.get("directPhone")
        or raw.get("Phone")
        or raw.get("phone")
    )
    if not phone_val and isinstance(raw.get("Phones"), list) and raw["Phones"]:
        first_phone = raw["Phones"][0]
        phone_val = first_phone.get("Value") if isinstance(first_phone, dict) else first_phone

    raw_contact_id = raw.get("ContactId") or raw.get("contactId")
    company_id = int(raw_contact_id) if raw_contact_id is not None else None

    return PersonDomainDTO(
        person_id=person_id,
        first_name=first_name,
        last_name=last_name,
        email=str(email_val) if email_val is not None else None,
        phone=str(phone_val) if phone_val is not None else None,
        company_id=company_id,
    )


def map_person_summary_row(raw: dict[str, Any]) -> PersonDomainDTO:
    """Map a SuperOffice Person archive row to PersonDomainDTO."""
    return map_person_entity(raw)


def map_ticket_message_row(
    raw: dict[str, Any], default_ticket_id: int | None = None
) -> TicketMessageDomainDTO:
    """Map a SuperOffice TicketMessage archive row to TicketMessageDomainDTO.

    Leaves attachments as an empty tuple `()` since archive rows do not embed
    attachment metadata (retrieved via ticket-level `list_attachments`).
    """
    message_id = int(raw.get("ticketMessageId") or raw.get("TicketMessageId") or raw.get("id") or 0)
    raw_tid = raw.get("ticketId") or raw.get("TicketId") or default_ticket_id or 0
    ticket_id = int(raw_tid)

    author = str(raw.get("author") or raw.get("Author") or "Support User")

    # Plain text extraction prioritizing plain body over HTML
    raw_body = raw.get("body") or raw.get("Body") or ""
    if not raw_body:
        raw_html = raw.get("htmlBody") or raw.get("HtmlBody") or ""
        body = html_to_plain_text(str(raw_html))
    else:
        body = str(raw_body).strip()

    created_at = _parse_datetime(raw.get("createdAt") or raw.get("CreatedAt"))

    return TicketMessageDomainDTO(
        message_id=message_id,
        ticket_id=ticket_id,
        author=author,
        author_type="CUSTOMER",  # Preserves Phase 2A DTO default without guessing
        body=body,
        created_at=created_at,
        attachments=(),
    )


def map_attachment_metadata(raw: dict[str, Any]) -> AttachmentMetadata:
    """Map a SuperOffice Attachment metadata response to AttachmentMetadata.

    Explicitly drops `AuthKey` (sensitive security token) and other unapproved properties.
    """
    attachment_id = raw.get("AttachmentId") or raw.get("attachmentId") or raw.get("id") or 0
    filename = str(raw.get("Name") or raw.get("name") or raw.get("filename") or "attachment")
    mime_type = str(
        raw.get("ContentType")
        or raw.get("contentType")
        or raw.get("mimeType")
        or "application/octet-stream"
    )
    raw_size = (
        raw.get("AttSize") or raw.get("attSize") or raw.get("size") or raw.get("sizeBytes") or 0
    )
    size_bytes = max(0, int(raw_size))
    md5_hash = str(raw.get("Md5") or raw.get("md5") or raw.get("md5_hash") or "")

    return AttachmentMetadata(
        attachment_id=attachment_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        md5_hash=md5_hash,
        is_content_authorized=False,
    )
