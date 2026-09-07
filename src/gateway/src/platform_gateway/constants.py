"""Constants for Gateway trusted headers and security boundaries."""

# Canonical internal headers propagated by Gateway to downstream MCP servers
INTERNAL_HEADER_CORRELATION_ID = "x-correlation-id"
INTERNAL_HEADER_USER_ID = "x-user-id"
INTERNAL_HEADER_USER_ROLE = "x-user-role"
INTERNAL_HEADER_PRODUCTION_WRITE = "x-production-write"
INTERNAL_HEADER_ATTACHMENT_ACCESS = "x-attachment-access"

# Set of internal identity & privilege headers that MUST be stripped if supplied by external callers
PROHIBITED_CALLER_HEADERS = frozenset(
    {
        INTERNAL_HEADER_USER_ID,
        INTERNAL_HEADER_USER_ROLE,
        INTERNAL_HEADER_PRODUCTION_WRITE,
        INTERNAL_HEADER_ATTACHMENT_ACCESS,
        "x-security-context",
        "x-principal-id",
        "x-caller-role",
    }
)
