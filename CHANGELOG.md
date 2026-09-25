# Changelog

All notable changes to the **SuperOffice AI Support MCP Platform** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **Phase B — Pre-Flight Health-Check Engine & Visual Connectivity Dashboard** (`platform_core.preflight`):
  - Comprehensive asynchronous diagnostic engine evaluating platform dependencies concurrently (`asyncio.gather`):
    - SuperOffice IIS Cluster: TCP reachability + HTTP GET status and IIS server detection, with hard tenant isolation checks (flags `osl-so-iis1.ls.local` violations).
    - MSSQL Telemetry: TCP 1433 reachability, authenticated `SELECT @@SERVERNAME, DB_NAME()` query, and tenant database name matching.
    - PostgreSQL Knowledge Base: TCP 5432 reachability, `pgvector` extension verification, and schema table counts.
    - SuperOffice Codebase Mirror: Filesystem path existence, structure, file count, and `manifest.json` verification.
    - Network Ports: Probes standard microservice ports (8000, 8001, 8002, 8003, 8005) to check availability or detect active running instances.
    - Security Perimeter: Evaluates JWT secret length (min 32 chars), placeholder detection, PII redaction, and attachment killswitch.
  - Terminal CLI runner (`uv run python -m platform_core.preflight`) with ANSI status badges, latency measurements, and exit codes.
  - Responsive visual web dashboard (`uv run python -m platform_core.preflight --gui` or `scripts/preflight-gui.ps1`) powered by Starlette and Uvicorn on `http://127.0.0.1:8088` with auto-browser launch and interactive re-run button.
  - PowerShell one-click runners: `scripts/check-preflight.ps1` and `scripts/preflight-gui.ps1`.
- **Phase A — Configuration Decomposition & Multi-Node Cluster Node Settings**:
  - Decomposed `KNOWLEDGE_DATABASE_URL` into discrete parameters (`KNOWLEDGE_DATABASE_HOST`, `PORT`, `NAME`, `USER`, `PASSWORD`, `SCHEMA`).
  - Automatic URL encoding via `quote_plus()` in `KnowledgeServerSettings.get_async_database_url()` to safely handle special characters (e.g. `@` in passwords).
  - Multi-node SuperOffice app server configuration via `SUPEROFFICE_APP_SERVERS` and `app_server_node_urls` property on `SuperOfficeServerSettings`.
  - Added unit test suites `test_decomposed_settings.py` and `test_app_servers_settings.py`.
- **SuperOffice Codebase Mirror & Synchronization Engine** (`so_mcp.sync`):
  - Dual extraction pipelines supporting authenticated HTTP (`scripts/customer.fcgi`) and direct read-only MSSQL queries.
  - Automated extraction of CRMScript / EJScript custom scripts, screen definitions, extra custom tables (`y_`), and configuration tables.
  - Built-in regex security scanner (`secret_scanner.py`) detecting passwords, API tokens, connection strings, and credentials before file write.
  - Windows/POSIX path and character sanitization (`sanitizer.py`).
  - Hierarchical folder mirror generation matching SuperOffice navigation trees and deterministic `manifest.json` output.
  - Operator synchronization CLI (`python -m so_mcp.sync.cli`) and PowerShell wrapper (`scripts/sync-so-codebase.ps1`).
- **Platform Gateway Prompts & AI Guardrails** (`platform_gateway.prompts`):
  - MCP Prompt protocol support (`prompts/list`, `prompts/get`) with reverse-proxy routing and in-memory TTL caching.
  - Three canonical prompt templates: `investigate_support_ticket`, `diagnose_mssql_health`, and `analyze_crmscript_error`.
  - Anti-hallucination guardrails: mandatory factual grounding, negative evidence interpretation rules (handling `CONNECTED` status and ring-buffer deadlock absence), and tool loop prevention.
- **SuperOffice STDIO Runtime Entrypoint** (`so_mcp.stdio`):
  - Direct STDIO runner (`python -m so_mcp.stdio`) for desktop MCP clients like Claude Desktop and Cursor.
- **Client Presentation Materials**:
  - Executive presentation deck (`SuperOffice_AI_Support_MCP_Client_Deck.pptx`) for stakeholder alignment and architectural walkthroughs.

### Changed
- **Tenant Isolation Enforcement**:
  - Enforced strict tenant cluster isolation for `SUPEROFFICE_APP_SERVERS`. Active environment explicitly excludes `osl-so-iis1.ls.local` because it connects to an alternate database on host `10.6.20.32`.
- **Exhaustive Environment Configuration Synchronization**:
  - Fully populated `.env` and `.env.example` across all 5 MCP servers and Gateway with commented-out optional path overrides to avoid Pydantic path coercion bugs.
- **Phase 7 — Controlled Two-Way Script Deployment & Safe Mutations**:
  - **PENDING / DEFERRED**: Formally postponed to maintain a strictly 100% `READ_ONLY` operational baseline, preventing unintended mutations or risk to tenant systems.
- **Architectural Boundary Enforcement**:
  - Enforced zero cross-server imports between `so_mcp` and `diag_mcp`, ensuring full fault-domain isolation verified by architectural contract tests.
- **Diagnostics & Investigation Enhancements**:
  - `find_deadlocks` tool enhanced with `hours_back` lookback window parameter mapped to UTC timestamp filtering.
  - Clarified tool descriptions for `search_logs` and `get_ticket_diagnostic_record` to actively prevent AI retry loops when backends are unconfigured or awaiting DBA schema verification.
  - Investigation service aggregator updated with diagnostic context enrichment.
- **Regression Test Suite**:
  - Expanded test baseline from 1,118 to **1,189 passing tests** (12 skipped opt-in live DB tests, 0 failures).
- Repository professionalization and provider-neutral hygiene updates (FLC.5B).
- Configuration-driven upstream endpoint detection in pre-flight development tooling.

---

## [v1.0.0-local.1] - 2026-09-09

### Summary
Initial **Local Development Release 1.0** checkpoint. Complete local development platform baseline establishing the Six-Layer Architecture, MCP Gateway perimeter, deny-by-default RBAC, 18 canonical public tools, and offline-verified diagnostic engines.

> [!NOTE]
> `v1.0.0-local.1` is a **LOCAL DEVELOPMENT** release verified for local testing and architecture evaluation. It is **not production-ready**.

### Added
- **MCP Gateway Layer**:
  - Streamable HTTP protocol support (ADR 007).
  - Reverse-proxy dispatcher and backend service registry.
  - Health check and runtime observability endpoints.
- **Security & Authorization Layer**:
  - Symmetric JWT authentication engine (HS256 local scope).
  - Declarative YAML-based RBAC engine (`tool_permissions.yaml`) enforcing deny-by-default.
  - Role hierarchy: L1 (Support Triage), L2 (System Diagnostics), L3 (Cross-System Investigation).
  - Response sanitization engine with automated PII and credential scrubbing.
  - Token bucket rate-limiting protection.
  - Attachment protection policy (Decision D05: metadata only; raw downloads prohibited).
- **SuperOffice MCP Server** (`so-mcp`, 8 tools):
  - Ticket query, search, message history, and attachment metadata retrieval.
  - Company and contact person search and retrieval with automatic PII masking.
  - Resilient asynchronous REST client with timeout and retry controls.
- **Diagnostics MCP Server** (`diag-mcp`, 6 tools):
  - MSSQL database health, top slow queries, system_health deadlock graph parser, and blocking session analysis.
  - Query safety invariants: 5-second statement timeout (D01), 50-row result cap (D02), mandatory `SNAPSHOT` isolation (D09).
  - Structured IIS W3C log reader and SuperOffice warning log parser.
  - Configuration-conditional execution for log search and registered ticket diagnostic schema.
- **Knowledge MCP Server** (`kb-mcp`, 3 tools):
  - PostgreSQL + `pgvector` knowledge repository and schema migrations.
  - Local in-process embeddings via `FastEmbedEmbeddingProvider` (`BAAI/bge-small-en-v1.5`, 384 dimensions).
  - Semantic vector search, operational runbook lookup, and known issue matching.
- **Knowledge Ingestion Pipeline & CLI**:
  - Immutable filesystem artifact storage (`approved/<type>/<id>/<hash>.md`).
  - Admission gate with multi-tier secret scanning and PII detection.
  - Transaction-scoped advisory locking (`pg_advisory_xact_lock`) for race-free ingestion.
  - Internal operator CLI (`python -m kb_mcp.ingestion.cli`) with `dry-run` and `ingest` commands.
- **Investigation MCP Server** (`investigation-mcp`, 1 composite tool):
  - Orchestrated incident investigation tool (`investigate_incident`) coordinating SuperOffice ticket data, database health, slow queries, and deadlock graphs.
- **Observability Layer**:
  - Cross-cutting structured logging, correlation IDs, and immutable audit event sinks.
- **Verification Suite**:
  - Full regression test suite with 1043 passing tests and 11 skipped live-DB tests.
  - Comprehensive static analysis and strict type checking (Ruff, Mypy).
