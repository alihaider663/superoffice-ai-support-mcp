# ADR 011: Python Foundation Architecture & Monorepo Design

**Date:** 2026-08-29  
**Status:** Accepted (Updated with Phase 1A Review Feedback)  
**Deciders:** Core Architecture Team, Platform Engineering  
**Consulted:** Security, SRE, AI Integration Team  
**Informed:** Development Teams  

---

## 1. Context & Problem Statement

The SuperOffice AI Support MCP Platform connects LLM clients (Claude Desktop, Cursor, Antigravity, and backend autonomous agents) to enterprise backend systems, including Onsite SuperOffice CRM REST WebAPIs, Microsoft SQL Server databases, Supabase vector stores, and host diagnostic infrastructure.

Following the Phase 1A Architecture Review:
1. **Transport Standard**: **ADR 007** mandates **Streamable HTTP** as the protocol transport across the entire platform. All stdio and legacy SSE transport ambiguities must be eliminated.
2. **MSSQL Access Strategy**: A rigorous evaluation is required to select the optimal database driver and interface between `aioodbc`, `pyodbc`, `SQLAlchemy`, and `Microsoft ODBC Driver 18`.
3. **Shared Investigation Framework**: A dedicated shared library (`platform-investigation`) is required for cross-system evidence aggregation, investigation orchestration, and incident correlation.
4. **CI/CD Lifecycle**: CI/CD pipeline automation is explicitly deferred to later phases.

---

## 2. Decision Drivers

- **Mandatory Streamable HTTP**: Full compliance with ADR 007 for streaming tool calls and standardized network transport.
- **Security & Privacy**: Strict perimeter defense at the Gateway, defense-in-depth on downstream servers, automated PII scrubbing, and attachment access gates.
- **Robust Database Safety**: Read-only parameterized database execution with enterprise connection pooling, hard statement timeouts, and bounded result sets.
- **Modularity & Independence**: MCP servers must be independently runnable and containerizable without tight coupling.
- **Unified Diagnostic Intelligence**: Shared investigation and correlation capabilities across disparate telemetry sources.

---

## 3. Decision

We adopt a **`uv` Workspace Monorepo Architecture** powered by **Python 3.12**, the **official Python MCP SDK (`mcp`)**, and **Pydantic v2**, structured as follows:

### 3.1 Technology Stack & Database Strategy
- **Runtime**: Python 3.12 (LTS) leveraging modern PEP 695 typing, improved `asyncio`, and runtime performance.
- **Protocol Transport (ADR 007)**: **Streamable HTTP** is mandatory for all MCP communication.
- **Protocol SDK**: Official `modelcontextprotocol/python-sdk` utilizing `mcp.server.fastmcp.FastMCP` over Streamable HTTP.
- **MSSQL Access Strategy**:
  - **Driver**: **Microsoft ODBC Driver 18 for SQL Server** (official, enterprise TLS 1.3 encryption, Kerberos/NTLM/SQL auth).
  - **Interface**: **SQLAlchemy 2.0 Async (`sqlalchemy[asyncio]`) with `aioodbc` dialect** (`mssql+aioodbc://`).
  - **Guarantees**: Enterprise-grade `AsyncAdaptedQueuePool` connection pooling with pre-ping health checks, structural parameterized query compilation (no raw SQL injection), automatic statement timeouts (`execution_options(timeout=5.0)`), hard row caps (50 rows), and `SNAPSHOT` transaction isolation (operational prerequisite: DBA confirms `ALLOW_SNAPSHOT_ISOLATION=ON`; no DDL executed by application).
- **HTTP Client**: `httpx` with async connection pooling, timeout guards, and custom transport hooks.
- **Knowledge Store**: `supabase-py` for Knowledge vector retrieval and runbook indexing.
- **Logging & Observability**: `structlog` emitting structured JSON to `stderr` with `contextvars`-backed correlation IDs.
- **Tooling**: `ruff` for unified linting/formatting; `mypy` for strict type checking; `pytest` + `respx` for offline testing.

### 3.2 Monorepo Package Topology
```text
src/
  gateway/                   # Security perimeter, auth gate & Streamable HTTP router
  servers/
    superoffice/             # CRM domain MCP server (Streamable HTTP)
    diagnostics/             # Read-only database & log diagnostics MCP server
    knowledge/               # Supabase vector search & runbook MCP server
    infrastructure/          # Host metrics & health MCP server
  shared/
    platform-investigation/  # Evidence aggregation, incident correlation & diagnostic workflows
    platform-core/           # Base types, domain models, error hierarchy
    platform-config/         # Typed Pydantic BaseSettings
    platform-security/       # RBAC, PII redaction, attachment gates
    platform-observability/  # JSON logging & audit emitters
    platform-http/           # Resilient HTTP client pool
```

### 3.3 Six-Layer Separation of Concerns
1. **MCP Layer**: Pure Streamable HTTP JSON-RPC protocol mapping and Pydantic schema validation.
2. **Security Layer**: RBAC evaluation, caller role validation, and PII masking.
3. **Investigation Layer (`platform-investigation`)**: Cross-system evidence aggregation, incident correlation, and diagnostic workflow state machines.
4. **Application Service Layer**: Domain logic, data aggregation, and entity mapping.
5. **Integration Layer**: Strongly typed client adapters for SuperOffice REST API, MSSQL (Async SQLAlchemy), and Supabase.
6. **Infrastructure Layer**: HTTP socket pools, database connection pools, and OS configuration resolution.

---

## 4. Alternatives Considered

| Alternative | Evaluation & Rationale for Rejection |
| :--- | :--- |
| **stdio / SSE Transports** | Rejected. ADR 007 establishes Streamable HTTP as the mandatory protocol transport for all local and distributed MCP services. |
| **Direct `pyodbc` Database Access** | Rejected. Direct `pyodbc` is synchronous and blocks the Python async event loop, requiring manual thread offloading and lacking enterprise connection pool health checks. |
| **Raw `aioodbc` without SQLAlchemy** | Rejected. Raw `aioodbc` lacks high-level statement timeout enforcement, connection recycling, and structural SQL parameter binding, increasing security and maintenance risk. |
| **Multi-Repository Architecture** | Rejected due to high overhead in cross-package versioning, split CI/CD pipelines, duplicated security logic, and difficult atomic refactorings across shared domain models. |
| **Arbitrary SQL Tooling for AI** | Strictly rejected due to severe security, data corruption, and unauthorized data extraction risks. All database interactions must flow through parameterized domain services. |

---

## 5. Consequences & Mitigations

### Positive Consequences
- **Strict Transport Compliance**: Eliminates protocol ambiguity by standardizing 100% on Streamable HTTP.
- **Enterprise Database Reliability**: SQLAlchemy 2.0 Async over Microsoft ODBC Driver 18 provides battle-tested connection pooling, automatic statement timeouts, and parameterized query safety.
- **Unified Diagnostic Intelligence**: `platform-investigation` provides a single reusable engine for aggregating evidence across CRM tickets, audit logs, and system metrics.
- **Zero Production Risk**: Offline test harness (`respx`, async SQLite) ensures complete test verification without live production dependencies.

### Trade-Offs & Mitigations
- *Trade-Off*: Async SQLAlchemy adds a dependency layer compared to raw database drivers.  
  *Mitigation*: The abstraction provides critical safety guarantees (connection health checks, query timeouts, parameterized statement compilation) that outweigh the minimal footprint.
