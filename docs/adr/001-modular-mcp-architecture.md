# ADR 001 — Modular MCP Architecture

## Status

Accepted

## Context

The SuperOffice AI Support MCP Platform must provide AI-assisted L1/L2/L3 support across SuperOffice and its supporting systems: application services, APIs, databases, infrastructure, and internal knowledge.

A single monolithic MCP server would combine unrelated domains — ticket operations, database diagnostics, infrastructure health, and knowledge retrieval — into one process, creating unclear ownership, a large attack surface, difficult independent testing, and inability to scale or deploy components independently.

The platform must also enforce strict security boundaries, support horizontal scaling, and remain independently testable per domain.

## Decision

Adopt a modular MCP architecture with four domain-specific MCP servers and one MCP Gateway:

1. **SuperOffice MCP** — SuperOffice business entities and ticket operations.
2. **Diagnostics MCP** — Application, API, and database diagnostics.
3. **Knowledge MCP** — Documentation, runbooks, known issues, and historical incidents.
4. **Infrastructure MCP** — Server health, service status, and infrastructure diagnostics.
5. **MCP Gateway** — Authentication, authorization, RBAC, policy enforcement, and audit logging.

Each MCP server has a clear ownership boundary. Cross-domain orchestration belongs in the Application Services layer, not inside MCP servers. Business logic belongs in Application Services. External-system communication belongs in Integration Clients. MCP tool handlers remain thin.

The architectural layering is:

```text
AI Agent
  → MCP Gateway
    → MCP Servers
      → Application Services
        → Integration Clients
          → External Systems
```

## Alternatives Considered

### Single Monolithic MCP Server

Rejected. Combines unrelated domains, creates an oversized attack surface, prevents independent scaling, complicates testing, and violates separation of concerns.

### Two-Server Split (Business vs. Technical)

Rejected. Insufficient separation — diagnostics, knowledge, and infrastructure have distinct ownership, security profiles, and scaling characteristics. Combining them creates the same ownership ambiguity at a smaller scale.

### Microservice-per-Tool Architecture

Rejected. Excessive operational overhead. The four-server model provides domain-level separation without fragmenting related capabilities into separate processes.

## Consequences

### Positive

- Clear domain ownership for every capability.
- Independent deployment and scaling per server.
- Smaller attack surface per server.
- Simplified testing — each server can be tested in isolation.
- RBAC can be scoped per server/tool.
- Failure isolation — one server's failure does not cascade to others.

### Negative

- Increased deployment complexity compared to a monolith.
- Requires a Gateway component for unified access control.
- Cross-domain investigations require coordination through Application Services.
- Operational monitoring spans multiple processes.

### Risks

- Capability misplacement — a tool may be added to the wrong server if ownership is not reviewed.
- Integration Client duplication — must be enforced through code review and architectural rules.