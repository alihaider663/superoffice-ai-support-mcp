This repository implements a production-grade SuperOffice AI Support MCP Platform.

Architectural layers:

AI Agent
→ MCP Gateway
→ MCP Servers
→ Application Services
→ Integration Clients
→ External Systems

MCP servers:

1. SuperOffice MCP
2. Diagnostics MCP
3. Knowledge MCP
4. Infrastructure MCP

Rules:

- MCP servers expose capabilities; they do not contain AI reasoning.
- Business logic belongs in application services.
- External-system access belongs in integration clients.
- Authorization belongs in deterministic security/policy code.
- Keep MCP servers stateless.
- Do not store durable investigation state in MCP process memory.
- Prefer typed Pydantic models.
- Prefer async I/O for external calls.
- Do not create giant multifunction tools.
- Do not duplicate integration clients.
- Maintain strict separation of concerns.
- Production deployments must support horizontal scaling.