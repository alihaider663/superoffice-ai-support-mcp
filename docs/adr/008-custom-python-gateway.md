# ADR 008 — Custom Python MCP Gateway

## Status

Accepted

## Context

The MCP Gateway is the primary security enforcement point for the platform (documented in `architecture.md` and `server-responsibilities.md`). It is responsible for:

- Authentication
- Authorization
- RBAC
- Tool-level permissions
- Policy enforcement
- Request validation
- Rate limiting
- Audit correlation
- Output filtering

The Gateway must understand **MCP protocol semantics** — specifically, it must identify which MCP tool is being invoked in each request and evaluate whether the authenticated identity's role permits that specific tool. This is not a standard HTTP routing decision; it requires parsing MCP protocol messages.

## Decision

Implement the MCP Gateway as a **custom Python service** using the project's established technology stack:

- Python 3.12+
- MCP Python SDK v2 (for MCP protocol handling)
- Pydantic (request/response validation, configuration models)
- httpx (async HTTP client for proxying to backend MCP servers)
- Structured logging (for audit trail)

### Gateway Request Flow

```text
Streamable HTTP request arrives
    │
    ▼
JWT validation (ADR 009)
    │
    ▼
Identity extraction (role, permissions from JWT claims)
    │
    ▼
MCP request parsing (identify target server + tool name)
    │
    ▼
Tool authorization (role ≥ tool.minimum_role?) (ADR 010)
    │
    ▼
Additional permission checks (production_write, attachment_access)
    │
    ▼
Rate limiting evaluation
    │
    ▼
Audit log entry (correlation ID, identity, server, tool, authorization result)
    │
    ▼
Proxy request to backend MCP server via httpx (Streamable HTTP)
    │
    ▼
Receive backend response
    │
    ▼
Output filtering (role-based field removal if applicable)
    │
    ▼
Audit log completion (result status, duration)
    │
    ▼
Return response to AI agent
```

### Gateway Boundaries

The Gateway does NOT:

- Contain SuperOffice business logic
- Contain AI reasoning
- Directly access SuperOffice, MSSQL, Supabase, or infrastructure systems
- Perform data transformation (belongs in Application Services)
- Issue JWT tokens (token issuance is an external concern)
- Store durable state (stateless — multiple instances behind a load balancer)

### High Availability

The Gateway is stateless. It loads configuration (tool permissions, JWT signing keys) at startup from files and environment variables. Multiple Gateway instances can run behind an HTTP load balancer. This mitigates the single-point-of-failure risk identified in the Phase 0 architecture review (Risk R1).

### Error Handling

The Gateway implements a global exception handler that sanitizes all error responses before they reach the AI agent. Internal errors (stack traces, connection strings, internal hostnames) are never exposed. The AI agent receives structured error responses with:

- Error category (authentication, authorization, validation, upstream, internal)
- Safe diagnostic message
- Correlation ID (for tracing in audit logs)

## Alternatives Considered

### API Gateway Product (Kong, Envoy, Traefik)

Rejected. Standard API gateways operate at the HTTP level (URL path, method, headers). They do not natively understand MCP protocol messages or MCP tool names. Achieving tool-level RBAC would require building custom plugins in the gateway's native language (Go for Kong/Traefik, C++ for Envoy), creating a second technology stack to maintain. The security-critical nature of this component favors full control in the project's primary language.

### Reverse Proxy with Middleware

Rejected. A reverse proxy (e.g., nginx) with custom middleware cannot parse MCP protocol messages to extract tool names for authorization decisions. MCP requests are JSON-RPC over HTTP — the tool name is inside the request body, not in the URL path. URL-based routing is insufficient for tool-level RBAC.

### MCP Proxy Pattern (Thin Protocol Proxy)

Partially adopted. The Gateway is essentially an MCP-aware proxy, but with significant security enforcement added. A "thin proxy" that only routes without enforcing authentication, authorization, and audit logging would not satisfy the security requirements. The custom Gateway is the MCP proxy pattern enhanced with the full security stack.

### No Gateway (Direct MCP Server Access)

Rejected. Without a Gateway, every MCP server would need to independently implement authentication, authorization, RBAC, audit logging, and rate limiting. This duplicates security-critical code across four servers, increases the attack surface, and makes security policy changes require coordinated updates across all servers. A centralized Gateway provides a single enforcement point.

## Consequences

### Positive

- Full MCP protocol awareness — can inspect tool names for authorization.
- Same technology stack as MCP servers — consistent development experience.
- Complete control over security enforcement logic.
- Centralized security policy — one place to update RBAC, rate limiting, audit configuration.
- Stateless design supports high availability and horizontal scaling.
- Global exception handler prevents internal information leakage.

### Negative

- Custom development effort — the Gateway must be built and maintained.
- The Gateway is security-critical — bugs in the Gateway affect the entire platform's security posture.
- Requires thorough testing (unit tests, security tests, MCP contract tests).
- Does not benefit from the operational maturity of established API gateway products.

### Risks

- Implementation complexity — the Gateway must correctly parse MCP protocol messages for every supported operation. This must be validated with MCP contract tests.
- Performance — the Gateway adds one network hop to every request. This should be negligible for the expected workload but must be monitored.
- Security regression — changes to the Gateway require security review (per the `security-review.md` workflow).
