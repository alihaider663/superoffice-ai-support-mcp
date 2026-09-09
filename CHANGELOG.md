# Changelog

All notable changes to the **SuperOffice AI Support MCP Platform** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed
- Repository professionalization and provider-neutral hygiene updates (FLC.5B).
- Configuration-driven upstream endpoint detection in pre-flight development tooling.
- Environment template expansion with complete MCP component defaults.

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
