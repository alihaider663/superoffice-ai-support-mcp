# SuperOffice AI Support MCP Platform

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![MCP Official SDK](https://img.shields.io/badge/MCP-Official%20SDK-orange.svg)](https://modelcontextprotocol.io/)
[![Status](https://img.shields.io/badge/Status-Local%20Development%20Release%201.0-brightgreen.svg)]()
[![Regression Tests](https://img.shields.io/badge/Tests-1142%20Passed-success.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An enterprise-grade, secure, modular Model Context Protocol (MCP) platform for AI-assisted SuperOffice CRM support triage, diagnostic telemetry, and cross-system incident investigation.

The platform bridges external LLM reasoning engines (such as Claude Desktop, Cursor, and autonomous support agents) with Onsite SuperOffice CRM REST APIs, Microsoft SQL Server database diagnostics, PostgreSQL/pgvector knowledge stores, and infrastructure boundaries under strict security, data minimization, and audit controls.

> [!NOTE]
> **Independent Integration Project & Trademark Notice**
> 
> This is an independent open-source integration project and is not an official SuperOffice product. SuperOffice and all other product names, logos, and brands are property of their respective owners. Mention of third-party trademarks does not imply endorsement, affiliation, or sponsorship.

> [!WARNING]
> **Production Boundary Disclaimer**
> 
> **Current Release:** `v1.0.0-local.1` (Local Development Release 1.0) — **COMPLETE / APPROVED**.  
> **Production Ready:** **NO**.  
> **Repository Professionalization:** IN PROGRESS (FLC.5C).  
> **Remote Publication:** NOT YET PERFORMED.  
> **Production Readiness Program:** FUTURE / NOT STARTED.  
> 
> This platform is verified strictly for **local development, offline testing, and architecture validation**. It does **not** claim live production deployment, production network trust, high availability, disaster recovery, or integration with enterprise secret managers.

---

## Architecture Overview

The platform strictly implements a **Six-Layer Architecture**. **Observability** is a cross-cutting concern spanning all operational layers:

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                           1. MCP Layer                                  │
│   (SuperOffice MCP, Diagnostics MCP, Knowledge MCP, Investigation MCP)  │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────v────────────────────────────────────┐
│                         2. Security Layer                               │
│  (MCP Gateway, JWT Auth, YAML RBAC, Privilege Flags, PII/Sanitization) │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────v────────────────────────────────────┐
│                      3. Investigation Layer                             │
│   (Investigation State Machine, Hypothesis Engine, Incident Correlator) │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────v────────────────────────────────────┐
│                  4. Application Service Layer                           │
│  (Ticket Investigation Service, Knowledge Service, Diagnostics Service) │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────v────────────────────────────────────┐
│                       5. Integration Layer                              │
│   (SuperOffice REST Client, MSSQL Async Client, Knowledge DB Adapter)  │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────v────────────────────────────────────┐
│                     6. Infrastructure Layer                             │
│       (Host Boundaries, Process Models, OS Diagnostics Boundaries)      │
└─────────────────────────────────────────────────────────────────────────┘
                                     ▲
                                     │
                     ════════════════╪════════════════
                        CROSS-CUTTING OBSERVABILITY
                     (Structured Logs, Audit Sinks, Traces)
                     ═════════════════════════════════
```

### Backend Ownership & Isolation Boundaries

Each backend is exclusively owned by a single service boundary. External AI models and LLMs have **zero direct access** to databases, filesystems, attachments, infrastructure shells, or enterprise credentials:
- **SuperOffice Business Data** $\rightarrow$ SuperOffice MCP (`so-mcp`) $\rightarrow$ SuperOffice REST API.
- **MSSQL Database Diagnostics & Logs** $\rightarrow$ Diagnostics MCP (`diag-mcp`) $\rightarrow$ Microsoft SQL Server & Log parsers.
- **Technical Knowledge & Runbooks** $\rightarrow$ Knowledge MCP (`kb-mcp`) $\rightarrow$ PostgreSQL + `pgvector`.
- **Infrastructure Boundaries** $\rightarrow$ Infrastructure MCP (`infra-mcp`, deferred under Decision D07).
- **Perimeter Security** $\rightarrow$ MCP Gateway (`platform-gateway`). The Gateway has **no direct database access**.

---

## Canonical Public Tool Inventory (23 Tools)

The Gateway exposes exactly **23 registered public tools** over Streamable HTTP ([ADR 007](docs/adr/007-gateway-protocol-selection.md)). There are zero aliases and zero public ingestion tools.

| Server | Tool Name | Minimum Role | Classification | Data Level | Description |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **SuperOffice MCP** | `get_ticket` | L1 | `READ_ONLY` | `INTERNAL` | Retrieve ticket details by ticket ID |
| | `search_tickets` | L1 | `READ_ONLY` | `INTERNAL` | Search tickets with criteria and pagination |
| | `get_ticket_messages` | L1 | `READ_ONLY` | `INTERNAL` | Retrieve communication messages on a ticket |
| | `list_attachments` | L1 | `READ_ONLY` | `INTERNAL` | List attachment **metadata** only (D05 enforced) |
| | `get_company` | L1 | `READ_ONLY` | `INTERNAL` | Retrieve company entity by company ID |
| | `find_companies` | L1 | `READ_ONLY` | `INTERNAL` | Search company directory |
| | `get_person` | L1 | `READ_ONLY` | `INTERNAL` | Retrieve contact person details (PII redacted) |
| | `find_persons` | L1 | `READ_ONLY` | `INTERNAL` | Search contact persons |
| | `sync_codebase` | L2 | `READ_ONLY` | `INTERNAL` | Mirror CRMScripts, screens, and database schemas locally |
| | `list_extra_tables` | L2 | `READ_ONLY` | `INTERNAL` | List user-defined `y_*` extra tables |
| | `get_extra_table_schema` | L2 | `READ_ONLY` | `INTERNAL` | Retrieve column schema and types for extra tables |
| | `query_extra_table` | L2 | `READ_ONLY` | `CONFIDENTIAL` | Bounded, parameterized read queries on extra tables |
| | `get_ticket_audit_trail` | L2 | `READ_ONLY` | `CONFIDENTIAL` | Chronological ticket audit trail, actions, and field changes |
| **Diagnostics MCP** | `get_database_health` | L2 | `READ_ONLY` | `CONFIDENTIAL` | Database health, DMV checks, uptime metrics |
| | `find_slow_queries` | L2 | `READ_ONLY` | `CONFIDENTIAL` | Identify top slow queries (max 50 rows, 5s timeout) |
| | `find_deadlocks` | L2 | `READ_ONLY` | `CONFIDENTIAL` | Parse deadlock graphs from system_health ring buffer |
| | `find_blocking_sessions`| L2 | `READ_ONLY` | `CONFIDENTIAL` | Analyze active blocking and wait resource chains |
| | `search_logs` | L2 | `READ_ONLY` | `CONFIDENTIAL` | Search IIS W3C & SuperOffice warning logs (config-conditional) |
| | `get_ticket_diagnostic_record` | L2 | `READ_ONLY` | `CONFIDENTIAL` | Database diagnostic records (active / live telemetry) |
| **Knowledge MCP** | `search_knowledge` | L1 | `READ_ONLY` | `INTERNAL` | Semantic vector search across technical documentation |
| | `get_runbook` | L1 | `READ_ONLY` | `INTERNAL` | Retrieve structured operational runbook by ID |
| | `find_known_issues` | L1 | `READ_ONLY` | `INTERNAL` | Search incident patterns and known workarounds |
| **Investigation MCP**| `investigate_incident` | L3 | `READ_ONLY` | `CONFIDENTIAL` | Orchestrated investigation (executes 4 subordinate tools) |

### Registered vs. Operational Status
- `search_logs`: `IMPLEMENTED / CONFIGURATION-CONDITIONAL` (operational when local log directories are configured).
- `get_ticket_diagnostic_record`: `ACTIVE / OPERATIONAL` (queries `ticket_log` and `ticket_log_action` with sanitized summaries).
- `get_ticket_audit_trail`: `ACTIVE / OPERATIONAL` (queries `ticket_log`, `ticket_log_action`, `ticket_log_change`, and `ejuser`).
- `list_extra_tables`, `get_extra_table_schema`, `query_extra_table`: `ACTIVE / OPERATIONAL` (user-defined `y_*` discovery).
- `Knowledge tools`: `CONFIGURED / LOCAL OPERATIONAL` (backed by local PostgreSQL + pgvector and FastEmbed).
- `investigate_incident`: Operational with 4 frozen subordinate operations (`get_ticket`, `get_database_health`, `find_slow_queries`, `find_deadlocks`). Subordinate `application_logs` returns `BLOCKED` and `knowledge_base` returns `NOT_CONFIGURED`.
- `Infrastructure MCP`: 0 public tools (retained as boundary; implementation deferred under Decision D07).

---

## Gateway Prompts & AI Guardrails (3 Prompts)

The MCP Gateway exposes structured, versioned prompt templates (`prompts/list`, `prompts/get`) with embedded operational rules and anti-hallucination guardrails:

| Prompt Name | Purpose | Key Guardrails & Arguments |
| :--- | :--- | :--- |
| `investigate_support_ticket` | End-to-end incident triage for a SuperOffice ticket | Factual grounding invariant, negative evidence rules (e.g. `CONNECTED` status doesn't disprove intermittent drops; zero deadlocks in lookback window doesn't prove zero contention), and tool loop prevention. Args: `ticket_id`, `include_db_diagnostics`, `hours_back`. |
| `diagnose_mssql_health` | Dedicated SQL Server health and performance triage | Enforces 5s statement timeout awareness, 50-row result caps, and SNAPSHOT isolation guidance. Args: `include_slow_queries`, `include_deadlocks`, `hours_back`. |
| `analyze_crmscript_error` | Custom SuperOffice CRMScript / EJScript debug flow | Analyzes syntax, runtime exceptions, and database interactions while guarding against arbitrary script execution. Args: `script_name`, `error_message`, `ticket_id`. |

---

## Security Model & Policy Invariants

- **Deny-by-Default RBAC**: Declarative tool-level policy defined in `tool_permissions.yaml` and enforced by `YamlPolicyEngine`. Unknown roles or unmapped tools are unconditionally rejected (`DENY`).
- **Role Hierarchy**: `L1` (Basic Support Triage) $\subset$ `L2` (Diagnostics) $\subset$ `L3` (Cross-System Investigation).
- **Attachment Protection (Decision D05)**: Deny-by-default. The public tool `list_attachments` returns strictly metadata. Raw attachment downloads and automatic ingestion to AI models are prohibited.
- **External AI Boundary (Decision D08)**: Live production transmission of confidential/sensitive SuperOffice CRM data to external AI endpoints is **NOT APPROVED**. Knowledge ingestion of live customer CRM exports is **DENIED**.
- **Database Safety (Decisions D01, D02, D09)**:
  - Statement timeout hard-capped at **5.0 seconds** (D01).
  - Query result rows hard-capped at **50 rows** (D02).
  - Mandatory **`SNAPSHOT`** isolation (D09). Zero `WITH (NOLOCK)` hints and zero dynamic/arbitrary SQL execution.
- **Data Minimization & PII Scrubbing**: All responses pass through recursive PII and secret redaction filters before delivery to external AI clients.

---

## Knowledge Backend & Ingestion Engine

- **Database**: PostgreSQL with `pgvector` (`0.8.6`) in schema `knowledge` (`documents`, `chunks`, `runbooks`, `known_issues`).
- **Embeddings**: In-process `FastEmbedEmbeddingProvider` utilizing `BAAI/bge-small-en-v1.5` (384 dimensions).
- **Immutable Artifacts**: Pre-redacted canonical Markdown artifacts stored at `approved/<type>/<id>/<hash>.md` on local filesystem outside Git.
- **Concurrency Control**: Transaction-scoped PostgreSQL advisory locking (`pg_advisory_xact_lock`) serializes ingest per document while computing embeddings outside the lock.
- **Internal Operator CLI**:
  ```bash
  # Execute dry-run admission and sanitization check
  python -m kb_mcp.ingestion.cli dry-run path/to/document.md

  # Ingest document into local knowledge base
  python -m kb_mcp.ingestion.cli ingest path/to/document.md
  ```
  Supported local formats: `.md`, `.markdown`, `.txt`, Runbook `.json`, Known-Issue `.json`. (PDF, DOCX, HTML, OCR, and YAML are deferred).

---

## SuperOffice Codebase Mirror & Synchronization Engine

The platform includes an automated synchronization engine (`so_mcp.sync`) that mirrors custom scripts, screen definitions, and database schemas from an Onsite SuperOffice instance to a local filesystem directory (e.g., `F:\CodeBase_SuperOffice`) for offline static analysis, indexing, and AI assistance:

- **Dual Extraction Modes**:
  - **`http`**: Extracts scripts, screens, and schemas via authenticated SuperOffice CRMScript handler (`scripts/customer.fcgi`).
  - **`mssql`**: Directly queries database metadata (`dbo.hierarchy`, `dbo.ejscript`, `dbo.screen_definition`, custom `y_` tables) with safety controls and zero cross-server dependencies.
- **Security & Secret Scanner**: Pre-scans every script body with regex pattern matchers for API keys, passwords, bearer tokens, connection strings, and base64 credentials before persisting to disk.
- **Deterministic Mirroring & Manifest**: Generates clean folder trees matching SuperOffice hierarchy paths, file sanitization for Windows/POSIX safety, and an immutable `manifest.json`.
- **Operator Commands**:
  ```powershell
  # Sync entire codebase using PowerShell helper
  .\scripts\sync-so-codebase.ps1 -OutputDir "F:\CodeBase_SuperOffice" -Mode http

  # Dry-run evaluation (no disk writes)
  .\scripts\sync-so-codebase.ps1 -DryRun -Verbose

  # Direct Python CLI
  uv run python -m so_mcp.sync.cli -o "F:\CodeBase_SuperOffice" -m http -t "ejscript,screens,schema"
  ```

---

## Client Integrations & Desktop Run Modes

- **Streamable HTTP (Multi-Client Gateway)**:
  Run the platform services via `.\scripts\start-local.ps1` and connect clients to the MCP Gateway at `http://127.0.0.1:8000/mcp`.
- **Direct STDIO Transport (Claude Desktop / Cursor)**:
  SuperOffice MCP can run directly over standard input/output without starting HTTP daemons:
  ```bash
  uv run python -m so_mcp.stdio
  ```
- **Stakeholder Presentation Deck**:
  A complete executive presentation deck is provided at [`SuperOffice_AI_Support_MCP_Client_Deck.pptx`](SuperOffice_AI_Support_MCP_Client_Deck.pptx) covering architecture, security boundaries, diagnostic workflows, and the local-to-production roadmap.

---

## Getting Started / Local Development

### Prerequisites
- Python `>= 3.12`
- `uv` package manager (`pip install uv` or install via official installer)
- PowerShell 7+ (on Windows) or Bash (on Linux/macOS)

### Setup Instructions
1. **Clone and Install**:
   ```bash
   uv sync
   ```

2. **Configure Local Environment**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` to configure your local test database endpoints and local development JWT secret.

3. **Pre-Flight Environment Check**:
   ```powershell
   powershell -File scripts/check-local.ps1
   ```

---

## Verification & Quality Baseline

The codebase maintains a 100% verified baseline with zero lint or type errors:

```bash
# Run full regression suite (1118 passed, 11 skipped live-DB tests)
uv run pytest

# Linting and style verification
uv run ruff check src tests
uv run ruff format --check src tests

# Strict type checking
uv run mypy src tests
```

---

## Local-Development-Only Exceptions

The local development setup incorporates specific exceptions that must be replaced in production:
1. **Self-Signed TLS Trust**: `SUPEROFFICE_ALLOW_SELF_SIGNED_CERT=true` for local test servers.
2. **MSSQL Certificate Trust**: `DIAGNOSTICS_MSSQL_TRUST_SERVER_CERTIFICATE=true` for local development SQL Server.
3. **Symmetric JWT Signing**: Local tests use `HS256` shared secrets; production requires asymmetric JWT validation / JWKS.
4. **Local Database & Cache**: Local PostgreSQL on `127.0.0.1:5432` and locally cached FastEmbed model weights.
5. **Local Artifact Store**: Knowledge artifacts stored in a local filesystem directory.

---

## Documentation Index

| Document | Description |
| :--- | :--- |
| [Project Status & Inventory](docs/project-status.md) | Authoritative platform status, gate history, tool inventory, and operational status |
| [Architecture Specification](docs/architecture.md) | Comprehensive Six-Layer Architecture, service topologies, and isolation boundaries |
| [Server Responsibilities](docs/server-responsibilities.md) | Individual MCP server boundaries, port allocations, and responsibility contracts |
| [Security Model & Threat Matrix](docs/security-model.md) | Threat modeling, RBAC policy definitions, data classification, and audit policies |
| [Investigation Flow](docs/investigation-flow.md) | Investigation Engine state machine, hypothesis evaluator, and incident timeline correlation |
| [Data Classification Guide](docs/data-classification.md) | Data level hierarchy (`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`) and handling rules |
| [Architecture Decision Records (ADRs)](docs/adr/) | Canonical architectural decisions (ADR 001 through ADR 012, Decision Ledger D01–D09) |
| [Security Policy](SECURITY.md) | Security vulnerability disclosure, responsible reporting, and boundary invariants |
| [Contributing Guide](CONTRIBUTING.md) | Contribution workflows, coding conventions, testing gates, and security rules |
| [Changelog](CHANGELOG.md) | Complete version history and milestone release notes |

---

## Roadmap

- **FLC.4**: Local Development Release 1.0 Checkpoint & Git Tag (`COMPLETE / APPROVED` — `v1.0.0-local.1`).
- **FLC.5**: Repository Professionalization & Remote Publication (Git history audit, provider-neutral hygiene, private repo push).
- **PR.0–PR.12**: Production Readiness Program (Production deployment, containerization, PKI, network policies, HA/DR, and operational acceptance).
