# ADR 004 — Stateless MCP Servers

## Status

Accepted

## Context

SuperOffice is deployed in a load-balanced environment. The AI Support MCP Platform must integrate with this existing infrastructure without introducing state management problems.

If MCP servers store durable investigation state in process memory, horizontal scaling becomes impossible: requests must be routed to the specific server instance holding the state, load balancing becomes sticky-session dependent, and server restarts lose investigation context.

The project architecture explicitly requires stateless MCP servers and support for horizontal scaling.

## Decision

MCP servers must be stateless.

### Rules

- Do not store durable investigation state in MCP server process memory.
- Do not rely on server-local caches for correctness.
- Durable state (investigation context, audit records, knowledge base entries) belongs in the application/data layer.
- Transient per-request state (request parsing, response assembly) is acceptable.
- Connection pooling is permitted as an infrastructure concern, not application state.

### Implications for Scaling

- Any MCP server instance can handle any request.
- Load balancers can use round-robin or least-connections routing.
- Server instances can be added or removed without state migration.
- Server restarts do not lose investigation context.
- Container orchestration can freely schedule MCP server containers.

### State Ownership

| State Type | Location |
|-----------|----------|
| Investigation context | Application/data layer (Supabase, external store) |
| Audit logs | Audit logging subsystem |
| Knowledge base | Knowledge data store (Supabase/pgvector) |
| Session/auth tokens | Gateway or external auth provider |
| Connection pools | Infrastructure layer (per-instance, non-durable) |
| Per-request context | In-flight request scope only |

## Alternatives Considered

### Stateful MCP Servers with Sticky Sessions

Rejected. Sticky sessions prevent true horizontal scaling, create single points of failure per session, complicate deployment, and conflict with the load-balanced SuperOffice environment.

### Distributed In-Memory Cache (Redis/Memcached) for MCP State

Rejected as a primary architecture. Adds infrastructure complexity and a potential single point of failure. The stateless design avoids the need for distributed state entirely. Caching may be used as an optimization layer in the future, but MCP servers must not depend on it for correctness.

### Event-Sourced MCP Servers

Rejected. Excessive complexity for the current requirements. Event sourcing is appropriate for systems that require full history replay, which is not a requirement for MCP tool execution.

## Consequences

### Positive

- True horizontal scaling — add or remove instances freely.
- Compatible with standard load balancers (no sticky sessions required).
- Server restarts are non-disruptive.
- Simplified deployment and container orchestration.
- Failure isolation — a crashed instance does not lose global state.

### Negative

- Multi-step investigations require the AI (or application service) to maintain context, not the MCP server.
- Some operations may require additional data-layer round trips that a stateful server could avoid.
- Connection pool configuration must be managed per-instance to avoid exceeding database connection limits under scale.

### Risks

- Connection pool exhaustion — if many stateless instances each maintain their own connection pool, the total connections may exceed database limits. Requires connection pooling strategy (see ADR 006).
- Implicit state leakage — developers may inadvertently introduce module-level mutable state. Requires code review enforcement.
