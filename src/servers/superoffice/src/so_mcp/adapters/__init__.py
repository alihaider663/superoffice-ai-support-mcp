"""SuperOffice integration adapter package."""

from so_mcp.adapters.factory import create_superoffice_client
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
from so_mcp.adapters.rest_client import SuperOfficeRestClient

__all__ = [
    "SuperOfficeRestClient",
    "create_superoffice_client",
    "deserialize_odata_page",
    "escape_archive_string_literal",
    "html_to_plain_text",
    "map_attachment_metadata",
    "map_contact_entity",
    "map_contact_summary_row",
    "map_person_entity",
    "map_person_summary_row",
    "map_ticket_entity",
    "map_ticket_message_row",
    "map_ticket_summary_row",
]
