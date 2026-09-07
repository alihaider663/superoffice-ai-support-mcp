"""SuperOffice OData pagination deserializer and archive string escaping utilities."""

import html
import re
from collections.abc import Callable
from typing import Any

from platform_core.models import PlatformBaseModel
from so_mcp.contracts.dtos import SuperOfficePageResponse


def escape_archive_string_literal(value: str) -> str:
    r"""Escape string literals for SuperOffice archive restriction syntax.

    SuperOffice archive restriction strings escape single quotes with a backslash (\')
    and backslashes with double backslash (\\).
    """
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return escaped.strip()


def html_to_plain_text(content: str) -> str:
    """Convert HTML content into sanitized plain text without external dependencies."""
    if not content:
        return ""
    # Normalize paragraph and line break tags into newlines
    text = re.sub(r"(?i)<br\s*/?>", "\n", content)
    text = re.sub(r"(?i)</?p\s*>", "\n", text)
    text = re.sub(r"(?i)</?div\s*>", "\n", text)
    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape HTML entities
    text = html.unescape(text)
    # Normalize multiple whitespace/newlines
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


def deserialize_odata_page[T: PlatformBaseModel](
    raw_data: dict[str, Any] | list[Any],
    item_mapper: Callable[[dict[str, Any]], T],
    page: int,
    page_size: int,
) -> SuperOfficePageResponse[T]:
    """Deserialize a SuperOffice OData archive response into a SuperOfficePageResponse.

    Uses official SuperOffice OData collection structure (`value` and `odata.nextLink`).
    """
    if isinstance(raw_data, list):
        items = tuple(item_mapper(x) for x in raw_data if isinstance(x, dict))
        next_link: str | None = None
    elif isinstance(raw_data, dict):
        raw_items = raw_data.get("value")
        if isinstance(raw_items, list):
            items = tuple(item_mapper(x) for x in raw_items if isinstance(x, dict))
        else:
            items = ()
        raw_next = raw_data.get("odata.nextLink") or raw_data.get("@odata.nextLink")
        next_link = str(raw_next) if raw_next else None
    else:
        items = ()
        next_link = None

    has_next_page = bool(next_link)

    return SuperOfficePageResponse[T](
        items=items,
        page=page,
        page_size=page_size,
        total_items=None,  # Not calculated by SuperOffice archive endpoints by default
        has_next_page=has_next_page,
    )
