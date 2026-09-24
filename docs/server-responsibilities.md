# MCP Server Responsibilities & Canonical Tool Surface

## 1. Overview of Platform Boundaries

The platform strictly separates responsibilities across dedicated MCP servers and architectural layers. Every capability has exactly one owner service.

The platform registers exactly **23 canonical public tools** at the Gateway perimeter. There are zero aliases and zero public ingestion tools.

```text
Platform Public Inventory: 23 Tools
├── SuperOffice MCP (13 tools)
├── Diagnostics MCP (6 tools)
├── Knowledge MCP (3 tools)
├── Investigation MCP (1 tool)
└── Infrastructure MCP (0 public tools — D07 Deferred)
```

---

## 2. SuperOffice MCP Server (`so-mcp`)

### Purpose
Provides controlled, read-only access to SuperOffice CRM entities and ticket operations via the SuperOffice REST WebAPI (v1) and read-only parameterized database queries for extra tables and audit trails.

### Owns
* Ticket retrieval and filtered search
* Ticket message / communication history
* Attachment metadata (Decision D05)
* Company entity retrieval and lookup
* Person / contact entity retrieval with PII masking
* User-defined `y_*` extra table discovery, schema inspection, and querying
* Ticket lifecycle audit trail, actions, and field transition history
* Local codebase synchronization for scripts, screens, and schemas

### Does NOT Own
* Diagnostic log inspection or host metrics
* AI reasoning or prompt synthesis
* Raw attachment downloads (deny-by-default)
* CRM write mutations (deferred in Local Development Release 1.0)
* Unvalidated dynamic or arbitrary SQL queries

### Canonical Public Tools (13)
1. `get_ticket`: Retrieve full ticket details by ticket ID.
2. `search_tickets`: Filtered ticket search with strict pagination.
3. `get_ticket_messages`: Retrieve messages / replies associated with a ticket.
4. `list_attachments`: Retrieve attachment **metadata** only (attachment ID, filename, content type, size).
5. `get_company`: Retrieve company details by company ID.
6. `find_companies`: Filtered search across company records.
7. `get_person`: Retrieve contact person details with PII masking.
8. `find_persons`: Filtered search across person records.
9. `sync_codebase`: Synchronize SuperOffice scripts, screens, and schemas to local directory.
10. `list_extra_tables`: Enumerate user-defined `y_*` extra tables.
11. `get_extra_table_schema`: Inspect columns, types, and primary keys of extra tables.
12. `query_extra_table`: Execute strictly bounded and parameterized reads on extra tables.
13. `get_ticket_audit_trail`: Chronological ticket audit trail, actions, and field changes.

### Operational Status
All 13 tools are **OPERATIONAL** in local development with live MSSQL database integration and test fixtures.

### Subsystems & Alternate Runtimes
- **Codebase Mirror & Synchronization Subsystem (`so_mcp.sync`)**:
  - Mirrors custom scripts (`ejscript`), screen definitions, and database schemas into a configured local directory (`SUPEROFFICE_CODEBASE_LOCAL_PATH`).
  - Supports dual extraction modes: authenticated HTTP (`scripts/customer.fcgi`) and direct read-only MSSQL.
  - Implements inline regex secret scanning and filesystem character sanitization.
  - Generates immutable `manifest.json` tracking file hashes and security alerts.
  - Managed via operator CLI (`python -m so_mcp.sync.cli`) or PowerShell script (`scripts/sync-so-codebase.ps1`).
- **Direct STDIO Entrypoint (`so_mcp.stdio`)**:
  - Provides a direct standard I/O application entrypoint for single-tenant desktop MCP clients (Claude Desktop, Cursor).

---

## 3. Diagnostics MCP Server (`diag-mcp`)

### Purpose
Provides technical diagnostic evidence across database health, query execution performance, deadlock history, and system logs.

### Owns
* Microsoft SQL Server DMV diagnostic inspection
* Slow query analysis (capped at 50 rows)
* Deadlock graph extraction from the `system_health` Extended Events ring buffer
* Active blocking session wait chains
* Local IIS W3C and SuperOffice warning log parsing

### Does NOT Own
* Arbitrary SQL query execution
* Database DDL or schema alterations
* DML mutations (`INSERT`, `UPDATE`, `DELETE`)
* General filesystem browsing outside configured log roots
* Direct SuperOffice business data logic

### Canonical Public Tools (6)
1. `get_database_health`: Returns SQL Server DMV health metrics, CPU utilization, and database status.
2. `find_slow_queries`: Returns top slow queries ordered by worker time / elapsed time (hard ceiling: 50 rows, 5s timeout).
3. `find_deadlocks`: Parses and returns deadlock graphs from the ring buffer.
4. `find_blocking_sessions`: Analyzes active blocking chains and waiting sessions.
5. `search_logs`: Searches local IIS W3C access logs and SuperOffice warning logs.
6. `get_ticket_diagnostic_record`: Correlates ticket IDs with database diagnostic records.

### Operational Status
- `get_database_health`, `find_slow_queries`, `find_deadlocks`, `find_blocking_sessions`: **OPERATIONAL** (live local SQL Server or mock repository).
- `search_logs`: **IMPLEMENTED / CONFIGURATION-CONDITIONAL** (operational when valid log root directory is configured; fails closed if enabled source fails).
- `get_ticket_diagnostic_record`: **OPERATIONAL** (live parameterized extraction against `ticket_log` and `ticket_log_action`).

---

## 4. Knowledge MCP Server (`kb-mcp`)

### Purpose
Provides semantic search and structured retrieval across technical documentation, operational runbooks, and verified known issues.

### Owns
* Vector search across documentation chunks in PostgreSQL + `pgvector`
* Structured runbook retrieval by unique identifier
* Known issue and incident pattern semantic lookup
* Internal offline ingestion pipeline and operator CLI

### Does NOT Own
* Public or unauthenticated ingestion tools (0 public ingestion tools)
* Customer CRM data or live ticket storage (Decision D08)
* Direct access to SuperOffice REST APIs or MSSQL databases

### Canonical Public Tools (3)
1. `search_knowledge`: Semantic vector search across technical documentation chunks (BAAI/bge-small-en-v1.5 embeddings).
2. `get_runbook`: Retrieves a structured operational runbook (steps, prerequisites, rollback) by ID.
3. `find_known_issues`: Semantic search across known issues, symptoms, root causes, and workarounds.

### Operational Status
All 3 tools are **CONFIGURED / LOCAL OPERATIONAL** against the local PostgreSQL `superoffice_ai_knowledge` database.

---

## 5. Investigation MCP Server (`investigation-mcp`)

### Purpose
Dedicated FastMCP microservice runtime (port 8005) hosting composite incident investigation workflows (ADR 012).

### Owns
* Composite incident investigation orchestration
* Layer-3 investigation state machine (`IncidentInvestigationStateMachine`)
* Request-scoped evidence aggregation and timeline building
* Hypothesis evaluation and confidence scoring
* Subordinate Streamable HTTP client dispatch to `so-mcp` and `diag-mcp`

### Does NOT Own
* Gateway security responsibilities (auth, RBAC, rate limiting)
* Direct database drivers or SQL connections
* Direct external network calls
* Durable cross-request persistence

### Canonical Public Tool (1)
1. `investigate_incident`: Orchestrates incident investigation using exactly 4 subordinate operations.

### Subordinate Composition & Evidence Status
- **Subordinate Operations (Exactly 4)**:
  1. `get_ticket` (`so-mcp`)
  2. `get_database_health` (`diag-mcp`)
  3. `find_slow_queries` (`diag-mcp`)
  4. `find_deadlocks` (`diag-mcp`)
- **Prohibited Subordinate Calls**: No calls to `search_tickets`, `find_blocking_sessions`, `search_logs`, or Knowledge MCP tools.
- **Evidence Collector Outcomes**:
  - `application_logs`: Returns `EvidenceOutcome.BLOCKED` (zero synthetic or fabricated log evidence).
  - `knowledge_base`: Returns `EvidenceOutcome.NOT_CONFIGURED` (zero synthetic or fabricated runbook evidence).

---

## 6. Infrastructure MCP Server (`infra-mcp`)

### Purpose
Structural server boundary reserved for controlled host and OS-level diagnostics.

### Canonical Public Tools (0)
- **0 public tools**.
- Implementation of detailed adapter contracts is **DEFERRED** under Decision `D07`.

### Candidate Future Probes (Roadmap)
- Host resource metrics (CPU load, memory pressure, disk volume space)
- IIS application pool status
- Windows service operational state

### Strict Prohibitions
- **NO arbitrary shell execution** (no cmd.exe, PowerShell, bash, or exec primitives).
- **NO general filesystem access** or directory navigation.
- **NO network scanning**, ping sweeps, or arbitrary socket connections.

---

## 7. MCP Gateway (`platform-gateway`)

### Purpose
Central security perimeter, caller authentication, RBAC policy enforcement, and Streamable HTTP protocol router.

### Gateway Owns
* JWT Bearer token validation and claims extraction
* Caller identity (`sub`), assigned role (`role`), and privilege flags (`production_write`, `attachment_access`)
* Declarative YAML RBAC policy evaluation (`tool_permissions.yaml`) under strict deny-by-default
* Per-identity and per-tool sliding-window rate limiting
* Correlation ID generation and propagation (`X-Correlation-ID`)
* Structured JSON audit logging of all allowed and denied tool invocations
* Streamable HTTP protocol routing to backend MCP servers
* Recursive output sanitization and PII scrubbing before returning responses to AI clients
* Canonical MCP Prompt registry & protocol routing (`prompts/list`, `prompts/get`) with TTL caching
* AI investigation guardrails (factual grounding invariant, negative evidence rules, and tool loop prevention)

### Gateway Does NOT Own
* SuperOffice business logic or entity transformations
* AI reasoning, prompt engineering, or LLM interaction
* Direct database connections (zero database drivers imported)
* JWT issuance (handled by external Identity Providers)
* Durable application state or session storage

---

## 8. Application Services (Layer 4)

### Purpose
Implements multi-source business workflows across integration clients:
* Ticket investigation service (`InvestigationApplicationService`)
* Knowledge retrieval service (`KnowledgeApplicationService`)
* Diagnostics application service (`DiagnosticsApplicationService`)

Application services operate behind interfaces, allowing complete isolation from protocol transport layers and full offline testability.

---

## 9. Integration Clients (Layer 5)

### Purpose
Encapsulates low-level communication with external backend systems:
* `SuperOfficeRestClient`: Async HTTP client with connection pooling, retries, and timeout guards.
* `MssqlRepository`: Async SQLAlchemy connection pool over Microsoft ODBC Driver 18 (`aioodbc`).
* `KnowledgePostgresRepository`: Async connection pool over PostgreSQL (`asyncpg`).

Integration clients must be completely isolated behind abstract domain interfaces and never called directly from MCP tool decorators without passing through application services.
