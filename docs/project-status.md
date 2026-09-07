# SuperOffice AI Support MCP Platform — Project Status & Approved Inventory

**Last Updated:** Phase 4.3 Implementation Completed  
**Current Phase:** `Phase 4 — Investigation MCP Exposure & Gateway Security Integration`  
**Phase 4.1 Status:** `COMPLETE / APPROVED`
**Phase 4.2 Status:** `COMPLETE / APPROVED`  
**Production Second-Hop Status:** `BLOCKED` (Pending infrastructure network policy enforcement)

---

## Current Unit Status

### Phase 2B — Runtime Adapter & Service Implementation
- **Phase 2B.1 — Core Security & Resilience Runtime Primitives**: `COMPLETE / APPROVED`
- **Phase 2B.2 — SuperOffice REST Runtime Adapter & Application Service**: `COMPLETE / APPROVED`
- **Phase 2B.3 — Diagnostics MSSQL / Log Runtime Adapter + Services**: `PARTIALLY IMPLEMENTED / BLOCKED ON EXTERNAL SOURCE SPECIFICATIONS`
- **Phase 2B.4 — Knowledge / Supabase Runtime Adapter + Services**: `PARTIALLY IMPLEMENTED / BLOCKED ON VERIFIED SUPABASE BACKEND SPECIFICATION`
- **Phase 2B.5 — Gateway Routing & Dispatch Runtime Engine**: `COMPLETE / APPROVED`

### Phase 3 — Investigation Engine & Diagnostic Orchestration Runtime
- **Phase 3.1 — Investigation State Machine & Orchestrator Runtime**: `COMPLETE / APPROVED`
- **Phase 3.2 — Generic Evidence Aggregator & Source Outcomes Runtime**: `COMPLETE / APPROVED`
- **Phase 3.3 — Incident Correlation & Investigation Timeline Runtime**: `COMPLETE / APPROVED`
- **Phase 3.4 — Hypothesis Evaluation Runtime**: `COMPLETE / APPROVED`
- **Phase 3.5 — Application Service Orchestration & End-to-End Investigation Integration**: `COMPLETE / APPROVED`

### Phase 4 — Investigation MCP Exposure & Gateway Security Integration
- **Phase 4.1 – Investigation MCP Runtime & Composition Architecture**: `COMPLETE / APPROVED`
- **Phase 4.2 – Public Investigation Tool Contract, Wire DTO & Serialization**: `COMPLETE / APPROVED-CANDIDATE`
- **Phase 4.3 — Gateway Routing, YAML RBAC & Rate Limiting**: `NOT STARTED`
- **Phase 4.4 — Official MCP SDK E2E & Security Verification**: `NOT STARTED`

---

## 1. Project Objective

The **SuperOffice AI Support MCP Platform** is an enterprise-grade AI-assisted diagnostic, support, and investigation system. It bridges LLM reasoning engines (Claude Desktop, Cursor, Antigravity, and autonomous support agents) with Onsite SuperOffice CRM instances, backend Microsoft SQL Server database clusters, Supabase knowledge stores, and infrastructure diagnostics, enabling fast, context-aware, and secure incident investigation.

---

## 2. Approved Scope & Tool Inventory (18 Approved / Blocked Runtime Tools)

1. **MCP Gateway**: Central perimeter security, caller authentication, RBAC policy enforcement, official Model Context Protocol (MCP) SDK runtime (`mcp.server.lowlevel.Server` and `mcp.server.streamable_http_manager.StreamableHTTPSessionManager`), and Streamable HTTP protocol routing via `mcp.client.streamable_http.streamable_http_client`.
2. **SuperOffice MCP Server** (8 approved read-only tools): `get_ticket`, `search_tickets`, `get_ticket_messages`, `list_attachments`, `get_company`, `find_companies`, `get_person`, `find_persons`. (Write mutations and raw attachment downloads remain unapproved/deferred).
3. **Diagnostics MCP Server** (6 tools): `get_database_health`, `find_slow_queries`, `find_deadlocks`, `find_blocking_sessions` (approved verified core); `get_ticket_diagnostic_record` and `search_logs` (failing closed pending external source specifications).
4. **Knowledge MCP Server** (3 tools): `search_knowledge`, `get_runbook`, `find_known_issues` (failing closed with `KnowledgeSearchError` pending Supabase backend schema verification).
5. **Infrastructure MCP Server** (0 runtime tools): Structural server slot retained (`TargetServer.INFRASTRUCTURE`); detailed probe capabilities remain deferred under Decision `2A-D07`.
6. **Investigation MCP Server** (`investigation-mcp`): Dedicated FastMCP microservice runtime hosting Layer-4 incident investigation orchestration over Streamable HTTP (`/mcp` port 8005). Employs `SuperOfficeMcpClientAdapter` and `DiagnosticsMcpClientAdapter` over internal Streamable HTTP. (Public tool `investigate_incident` implemented in Phase 4.2; Gateway routing, YAML RBAC [L3/READ_ONLY/CONFIDENTIAL], minimal headers, and rate limiting implemented in Phase 4.3. Gateway canonical active inventory is exactly 18).
7. **Shared Enterprise Libraries**: Standardized error hierarchy, Pydantic typed settings, structured logging (`structlog`), security/PII redaction abstractions, resilient HTTP client abstractions, diagnostic investigation state machine, multi-source evidence aggregation runtime (`platform_investigation`), and Layer-4 application service (`platform_investigation_service`).

---

## 3. Network Architecture & Security Invariants

### Downstream Trust Model & Second-Hop Policy
- Gateway-generated identity and privilege headers (`X-User-ID`, `X-User-Role`, `X-Production-Write`, `X-Attachment-Access`, `X-Correlation-ID`) are trusted internal transport context derived exclusively from validated Gateway `SecurityContext`.
- In Phase 4.1, backend MCP servers (`so-mcp`, `diag-mcp`) contain no inbound correlation or identity consumers. Therefore, downstream adapter invocations pass a strictly **EMPTY** custom header set.
  - `X-Correlation-ID`: NOT relayed in Phase 4.1 (trace-header relay deferred until backend inbound correlation propagation is explicitly implemented).
  - `X-User-ID`, `X-User-Role`, `X-Production-Write`, and `X-Attachment-Access` are **NOT relayed**.
- Raw external Bearer JWTs terminate strictly at the Gateway and are never passed on internal second-hop calls.

### Mandatory Backend Reachability Invariant & Second-Hop Enablement
Production backend MCP endpoints MUST NOT be directly reachable from AI clients or untrusted networks.
- External MCP clients communicate only with the Gateway.
- Backend MCP ports must be restricted through deployment/network controls (e.g., Kubernetes `NetworkPolicy`, VPC private subnets) so that only authorized callers (`gateway`, `investigation-mcp`) can reach them.
- **Production Enablement Prerequisite**: Live production second-hop traffic is **BLOCKED** until deployment network policy enforcement is provisioned. Local development and automated tests run against local/synthetic fixtures.

### DNS Rebinding & Host-Header Protection Scope
`TransportSecuritySettings` and `allowed_hosts` provide DNS rebinding and Host-Origin header protection at the FastMCP server edge. They do **not** provide authentication or authorization. Centralized JWT authentication and RBAC authorization remain strictly enforced at the Gateway.

---

## 4. Architecture Decisions Register

| Decision ID | Area | Subject | Status | Resolution / Invariants |
| :--- | :--- | :--- | :--- | :--- |
| `2A-D01` | Diagnostics MSSQL | Statement Query Timeout | **RESOLVED** | **5 seconds** (`DIAGNOSTICS_MSSQL_QUERY_TIMEOUT_SECONDS=5`). Database query safety ceiling. |
| `2A-D02` | Diagnostics MSSQL | Maximum Result Rows | **RESOLVED** | **50 rows** (`DIAGNOSTICS_MSSQL_MAX_ROWS=50`). Hard safety ceiling enforced at query/runtime. |
| `2A-D04` | SuperOffice | Attachment MD5 Metadata | **OPEN** | Attachment MD5 discrepancy remains unresolved. Runtime behavior remains `md5_hash=None`. Non-blocking. |
| `2A-D06` | Logging | Documentation Normalization | **NON-BLOCKING** | Documentation discrepancy; `platform-observability` runtime stream behavior unchanged. |
| `2A-D07` | Infrastructure | Infrastructure Adapter Contracts | **DEFERRED** | Infrastructure detailed adapter contracts remain deferred. No unapproved probe capabilities are exposed at runtime. |
| `2A-D08` | AI Boundary | AI Provider / Data Processing Boundary | **OPEN / ENFORCED** | Live production CRM transmission to external AI endpoints blocked pending DPIA. |
| `2A-D09` | Diagnostics MSSQL | Transaction Isolation | **RESOLVED** | **SNAPSHOT** isolation mandatory. Operational prerequisite: DBA must confirm `ALLOW_SNAPSHOT_ISOLATION=ON`. The application will not execute DDL (`ALTER DATABASE`). No automatic `READ UNCOMMITTED` fallback and zero `WITH (NOLOCK)` hints approved. |
| `2A-DOC-01` | Documentation | TimeoutError Class Hierarchy Doc Sync | **RECONCILED** | Documentation synchronized with implementation. |
| `ADR-012` | Investigation MCP | Service Identity, Delegation & Composition | **ACCEPTED / ENFORCED** | Dedicated `investigation-mcp` service; official Streamable HTTP composition; Network-Bound Caller Authorization; Gateway remains sole RBAC authority; L3 composite minimum role baseline; frozen 4 subordinate capabilities; strictly EMPTY second-hop custom header set (no correlation/privilege headers); request-scoped ephemeral state; zero Gateway imports; zero database drivers. Production second-hop enablement blocked pending network policy provisioning. |

---

## 5. External Blockers & Pending Dependencies Register

| Blocker ID | Affected Tool | Dependency Owner | Nature of Block | Fallback Behavior |
| :--- | :--- | :--- | :--- | :--- |
| `BLK-2B3-01` | `get_ticket_diagnostic_record` | DBA / SuperOffice Schema Owner | Database table/view names and ticket FK relationships unverified | Returns `PHASE_2B_3_BLOCKED_SCHEMA` |
| `BLK-2B3-02` | `search_logs` | Infrastructure / App Ops | Log storage engine (Elastic, Loki, Seq, MSSQL) unverified | Returns `PHASE_2B_3_BLOCKED_LOG_BACKEND` |
| `BLK-2B4-01` | `search_knowledge`, `get_runbook`, `find_known_issues` | Knowledge Admin / Supabase Owner | Supabase physical schema / PostgREST endpoints unverified | Returns `KNOWLEDGE_BACKEND_NOT_CONFIGURED` |
| `BLK-4.1-01` | `investigation-mcp` production second hop | Infrastructure / Security Ops | Network policy / subnet firewall rules restricting backend MCP reachability to Gateway and Investigation MCP | Production second-hop traffic BLOCKED |

---

## 6. Verification Harness & Quality Gate Results

- **Total Automated Tests**: **499 passed offline** (100% pass rate)
  - Generic Phase 3 (Layer 3) investigation tests: **93 passed**
  - Layer-4 Phase 3.5 service & integration tests: **50 passed** (49 unit + 1 integration)
  - Phase 4.1 & Phase 4.2 Investigation MCP tests (`tests/unit/investigation_mcp/`): **102 passed** (37 Phase 4.1 + 65 Phase 4.2)
  - Combined Investigation suite (Layer 3 + Layer 4 + Layer 1 host): **245 passed**
- **Static Lint (Ruff)**: **0 errors** across `src/` and `tests/`
- **Strict Type Check (Mypy)**: **0 issues across 187 source files**
- **Measured Line Coverage**:
  - `platform_investigation`: **100% measured line coverage** (406 stmts)
  - `platform_investigation_service`: **100% measured line coverage** (271 stmts)
  - `investigation_mcp`: **100% measured line coverage** (493 stmts)
  - `platform_gateway`: **84% measured line coverage**
  - `diag_mcp`: **90% measured line coverage**
  - `kb_mcp`: **89% measured line coverage** (94% excluding server entrypoint `main.py`)
