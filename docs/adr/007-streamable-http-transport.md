# ADR 007 — Streamable HTTP Transport

## Status

Accepted

## Context

The SuperOffice AI Support MCP Platform requires a transport mechanism for communication between the AI agent, the MCP Gateway, and the backend MCP servers. The platform must support:

- Stateless MCP servers (ADR 004)
- Horizontal scaling behind load balancers
- Container-friendly deployment (project requirements)
- The MCP Gateway as a network-accessible security boundary (ADR 008)
- Independent deployment of MCP servers

The MCP Python SDK v2 supports multiple transports: stdio, SSE (Server-Sent Events), and Streamable HTTP.

## Decision

Use **Streamable HTTP** as the MCP transport protocol for all environments (development and production).

**stdio** is permitted only for isolated unit testing of individual MCP servers where no network communication is involved.

### Communication Path

```text
AI Agent
    │
    │  Streamable HTTP (with JWT Bearer token)
    ▼
MCP Gateway (HTTP endpoint)
    │
    │  Streamable HTTP (internal network)
    ▼
Backend MCP Server (HTTP endpoint)
```

### Configuration

Each MCP server exposes an HTTP endpoint. The Gateway maintains a registry of backend MCP server URLs:

```text
Gateway          →  http://gateway:8000
SuperOffice MCP  →  http://superoffice-mcp:8001
Diagnostics MCP  →  http://diagnostics-mcp:8002
Knowledge MCP    →  http://knowledge-mcp:8003
Infrastructure MCP → http://infrastructure-mcp:8004
```

Port assignments and hostnames are configurable via environment variables.

## Alternatives Considered

### stdio Everywhere

Rejected. stdio is process-local — it cannot cross network boundaries, cannot be load-balanced, and requires all components to run on the same host. This directly conflicts with horizontal scaling (ADR 004) and independent deployment requirements.

### SSE (Server-Sent Events)

Rejected. SSE is a legacy MCP transport being superseded by Streamable HTTP in the MCP specification. Streamable HTTP subsumes SSE's streaming capability while also supporting stateless request/response. Adopting SSE would mean adopting a transport on a deprecation path.

### gRPC

Rejected. gRPC adds a separate serialization format (Protocol Buffers) and toolchain. The MCP specification defines its own protocol format. Using gRPC would require translating between MCP messages and protobuf definitions, adding complexity without clear benefit. The platform's approved technology stack is Python + HTTP.

## Consequences

### Positive

- Compatible with any HTTP load balancer (no sticky sessions, no special protocols).
- Stateless request/response model aligns with ADR 004.
- Standard HTTP infrastructure tooling applies (monitoring, logging, TLS).
- MCP SDK v2 provides native Streamable HTTP support — no custom transport implementation required.
- Gateway can be deployed as a standard HTTP service.
- Backend MCP servers can be independently deployed, scaled, and health-checked via HTTP.

### Negative

- Requires each MCP server to bind an HTTP port (slightly more configuration than stdio).
- HTTP overhead compared to stdio for same-host communication (negligible for this workload).
- Internal network communication between Gateway and backend MCP servers should be TLS-encrypted in production, adding certificate management.

### Risks

- Internal network security — communication between the Gateway and backend MCP servers traverses the internal network. In production, this should be encrypted (TLS) and network-isolated. This is an operational concern, not an architectural limitation.
