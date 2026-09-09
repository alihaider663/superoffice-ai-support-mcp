# SuperOffice AI Support MCP Platform — Project Status & Approved Inventory

**Project:** SuperOffice AI Support MCP Platform  
**Authoritative Repository:** `F:\superoffice-ai-support-mcp`  
**Implementation Baseline Before FLC.3 Documentation:** `ef009689980d5586e23029d6ed2d31840e6a34f7`  
**FLC.3 Documentation Checkpoint:** `bc070d62fddec52ecdb4765ecbfa2494a423167f`  
**Release Target:** `Local Development Release 1.0`  
**Release Identifier:** `v1.0.0-local.1`  
**Current Release Status:** `LOCAL DEVELOPMENT RELEASE 1.0 COMPLETE / APPROVED`  
**Completed Closure Gates:**  
- **FLC.1 — Gateway → Knowledge E2E:** `COMPLETE / APPROVED`  
- **FLC.2 — Full Local Platform Regression & Security Review:** `COMPLETE / APPROVED`  
- **FLC.3 — Decision Ledger / Deferred Items / Documentation Reconciliation:** `COMPLETE / APPROVED / CHECKPOINTED`  
- **FLC.4 — Local Development Release 1.0 Checkpoint & Tag:** `COMPLETE / APPROVED`  
**Next Gate:** `FLC.5 — Repository Professionalization & Remote Publication` (`NOT STARTED`)  
**Production Ready:** `NO`  
**Production Deployment / Network Trust:** `NOT STARTED`  
**Production Readiness Program:** `FUTURE / NOT STARTED`  

---

## 1. Executive Summary & Release Status

The **SuperOffice AI Support MCP Platform** is an enterprise-grade AI-assisted diagnostic, support, and investigation platform. It provides a secure, modular interface connecting external LLM clients and autonomous support agents with Onsite SuperOffice CRM instances, Microsoft SQL Server database clusters, local PostgreSQL + pgvector knowledge stores, and infrastructure boundaries.

### Release Status Definition
- **Scope**: Local Development Release 1.0 only.
- **Operational Reality**: All components, servers, routers, security policies, and ingestion pipelines are designed, verified, and operational for local development and offline testing.
- **Production Status**: Production deployment, production network trust, production secret stores, and external AI transmission of confidential CRM data are **NOT STARTED** and remain strictly outside the claims of this local release.

---

## 2. Completed Phase History

| Phase / Gate | Description | Status |
| :--- | :--- | :--- |
| **Phase 0** | Conceptual foundation, problem definition, and initial architecture requirements | `COMPLETE / APPROVED` |
| **Phase 0.5** | Core ADR decisions (ADR 007–010: Transport, Gateway, Auth, RBAC) | `COMPLETE / APPROVED` |
| **Phase 2A** | Architecture review, formal constraints, decisions 2A-D01–2A-D09 | `COMPLETE / APPROVED` |
| **Phase 3** | Investigation Engine runtime, hypothesis evaluation, timeline correlation | `COMPLETE / APPROVED` |
| **Phase 4** | Investigation MCP microservice (`investigation-mcp`), ADR 012 composition | `COMPLETE / APPROVED` |
| **Local Product Readiness** | Foundation integration, local package configuration, developer experience | `COMPLETE / APPROVED` |
| **Part 6** | Full platform security verification, rate limiting, and output sanitization | `COMPLETE / APPROVED` |
| **7A** | Knowledge PostgreSQL + pgvector schema design, migration, and connection pooling | `COMPLETE / APPROVED` |
| **7B.1** | Knowledge MCP runtime service, FastEmbed integration, vector search implementation | `COMPLETE / APPROVED` |
| **7C.1** | Knowledge MCP tool contracts (`search_knowledge`, `get_runbook`, `find_known_issues`) | `COMPLETE / APPROVED` |
| **7D.1** | Knowledge ingestion architecture, admission gate, and secret scanner foundations | `COMPLETE / APPROVED` |
| **7D.2** | Secret scanner & PII detection boundary implementation | `COMPLETE / APPROVED` |
| **7D.3** | Content normalization and parser admission pipelines | `COMPLETE / APPROVED` |
| **7D.4** | Deterministic chunking, SHA-256 provenance, and embedding pipeline | `COMPLETE / APPROVED` |
| **7D.5A** | Transactional PostgreSQL repository & advisory locking engine | `COMPLETE / APPROVED` |
| **7D.5B** | Admission & sanitization boundary integration | `COMPLETE / APPROVED` |
| **7D.5C** | Canonical identity & immutable file-based artifact store (`.md` layout) | `COMPLETE / APPROVED` |
| **7D.5D** | Chunking, local FastEmbed embeddings, and transactional DB persistence | `COMPLETE / APPROVED` |
| **7D.5E** | Internal operator CLI (`dry-run`, `ingest`) & full local ingestion E2E | `COMPLETE / APPROVED` |
| **FLC.1** | Gateway → Knowledge E2E verification (Client → Gateway → Knowledge → DB) | `COMPLETE / APPROVED` |
| **FLC.2** | Full local platform regression & security review (1043 passed, 11 skipped) | `COMPLETE / APPROVED` |
| **FLC.3** | Decision Ledger, Deferred Items & Documentation Reconciliation | `COMPLETE / APPROVED / CHECKPOINTED` |
| **FLC.4** | Local Development Release 1.0 Checkpoint & Tag | `COMPLETE / APPROVED` |
| **FLC.5** | Repository Professionalization & Remote Publication | `NOT STARTED` |
| **PR.0–PR.12** | Production Readiness Program | `FUTURE / NOT STARTED` |

---

## 3. Six-Layer Architecture Specification

The platform architecture strictly enforces a **Six-Layer Architecture**. Observability is a **cross-cutting concern** that spans all operational layers; it is never designated as a separate sequential layer (there is no "Layer 7 Observability").

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

### Layer Definitions
1. **MCP Layer**: Official Model Context Protocol runtimes exposing safe, minimized tools over Streamable HTTP.
2. **Security Layer**: Central perimeter enforcement, token validation, caller identity extraction, RBAC authorization, and data sanitization.
3. **Investigation Layer**: Domain reasoning, state machine transitions, evidence correlation, and hypothesis validation.
4. **Application Service Layer**: Orchestration of business workflows, runbook retrieval, and diagnostic aggregation.
5. **Integration Layer**: Typed, resilient outbound client adapters communicating with backend systems.
6. **Infrastructure Layer**: Host OS isolation, network policies, process lifecycles, and hardware boundaries.
- **Cross-Cutting Observability**: Contextual JSON structured logging (`structlog`), correlation IDs (`X-Correlation-ID`), audit trails, and execution timing spanning all layers without breaking layer hierarchy.

---

## 4. Backend Ownership & Isolation Boundaries

To guarantee security and data minimization, each backend data source is exclusively owned by exactly one service boundary:

| Backend Resource | Sole Owner Service | Integration Protocol | Direct AI Access | Direct Gateway Access |
| :--- | :--- | :--- | :--- | :--- |
| **SuperOffice Business Data** | SuperOffice MCP Server (`so-mcp`) | SuperOffice REST WebAPI (v1) | **PROHIBITED** | **NO** |
| **MSSQL Database Diagnostics** | Diagnostics MCP Server (`diag-mcp`) | SQLAlchemy 2.0 Async / `aioodbc` | **PROHIBITED** | **NO** |
| **Application & API Logs** | Diagnostics MCP Server (`diag-mcp`) | Filesystem / W3C Parser | **PROHIBITED** | **NO** |
| **Technical Knowledge & Runbooks** | Knowledge MCP Server (`kb-mcp`) | PostgreSQL + pgvector (`asyncpg`) | **PROHIBITED** | **NO** |
| **Host & System Diagnostics** | Infrastructure MCP Server (Boundary) | OS / Host Primitives | **PROHIBITED** | **NO** |

### Strict Isolation Invariants
- **No Direct AI Database Access**: AI clients and LLMs have zero direct network, protocol, or credential access to MSSQL, PostgreSQL, SuperOffice APIs, raw attachment files, or host shells.
- **No Direct Gateway Database Access**: The Gateway does not import database drivers, does not establish database connection pools, and does not execute database queries. It routes requests exclusively via Streamable HTTP.
- **No Direct Filesystem / Shell Access**: No tool provides arbitrary shell execution, general directory browsing, or raw file retrieval.

---

## 5. Canonical Public Tool Inventory (Total 18)

The platform exposes exactly **18 canonical public tools** registered at the Gateway perimeter. There are zero aliases and zero public ingestion tools.

```text
SuperOffice MCP (8)    Diagnostics MCP (6)    Knowledge MCP (3)    Investigation MCP (1)
───────────────────    ───────────────────    ─────────────────    ─────────────────────
get_ticket             get_database_health    search_knowledge     investigate_incident
search_tickets         find_slow_queries      get_runbook
get_ticket_messages    find_deadlocks         find_known_issues
list_attachments       find_blocking_sessions
get_company            search_logs
find_companies         get_ticket_diagnostic_record
get_person
find_persons
```

- **Infrastructure MCP**: 0 public tools (structural slot retained; implementation deferred under Decision `D07`).
- **Public Ingestion**: 0 public tools (Knowledge ingestion is an internal operator CLI only).

---

## 6. Registered Inventory vs. Current Operational Status

The platform strictly distinguishes between **registered public contract inventory** and **current local operational status**. Not all 18 registered tools are operational in the local development environment:

| Tool Name | Server | Role / Classification / Level | Current Local Operational Status | Notes / Operational Reality |
| :--- | :--- | :--- | :--- | :--- |
| `get_ticket` | SuperOffice | L1 / READ_ONLY / INTERNAL | **OPERATIONAL** | Mocked/Stubbed REST client in local test suite. |
| `search_tickets` | SuperOffice | L1 / READ_ONLY / INTERNAL | **OPERATIONAL** | Parameterized search with strict pagination. |
| `get_ticket_messages` | SuperOffice | L1 / READ_ONLY / INTERNAL | **OPERATIONAL** | Read-only ticket communication history. |
| `list_attachments` | SuperOffice | L1 / READ_ONLY / INTERNAL | **OPERATIONAL** | **Metadata only** (Decision D05 enforced). |
| `get_company` | SuperOffice | L1 / READ_ONLY / INTERNAL | **OPERATIONAL** | Company master entity lookup. |
| `find_companies` | SuperOffice | L1 / READ_ONLY / INTERNAL | **OPERATIONAL** | Filtered search over company records. |
| `get_person` | SuperOffice | L1 / READ_ONLY / INTERNAL | **OPERATIONAL** | Person / Contact lookup with PII redaction. |
| `find_persons` | SuperOffice | L1 / READ_ONLY / INTERNAL | **OPERATIONAL** | Filtered search over person records. |
| `get_database_health` | Diagnostics | L2 / READ_ONLY / CONFIDENTIAL | **OPERATIONAL** | Live/Mock MSSQL DMV checks (5s timeout, SNAPSHOT). |
| `find_slow_queries` | Diagnostics | L2 / READ_ONLY / CONFIDENTIAL | **OPERATIONAL** | Live/Mock DMV query analysis (capped at 50 rows). |
| `find_deadlocks` | Diagnostics | L2 / READ_ONLY / CONFIDENTIAL | **OPERATIONAL** | Live/Mock system_health ring buffer parser. |
| `find_blocking_sessions`| Diagnostics | L2 / READ_ONLY / CONFIDENTIAL | **OPERATIONAL** | Live/Mock session wait analysis. |
| `search_logs` | Diagnostics | L2 / READ_ONLY / CONFIDENTIAL | **IMPLEMENTED / CONFIG-CONDITIONAL** | Operational when log directory configured; fails closed if enabled source fails. |
| `get_ticket_diagnostic_record` | Diagnostics | L2 / READ_ONLY / CONFIDENTIAL | **REGISTERED / BLOCKED** | Fails closed with `DIAGNOSTIC_SCHEMA_NOT_CONFIGURED` pending DBA table schema verification. |
| `search_knowledge` | Knowledge | L1 / READ_ONLY / INTERNAL | **CONFIGURED / LOCAL OPERATIONAL** | Local PostgreSQL + pgvector + FastEmbed (384-dim). |
| `get_runbook` | Knowledge | L1 / READ_ONLY / INTERNAL | **CONFIGURED / LOCAL OPERATIONAL** | Fetches verified structured runbooks by ID. |
| `find_known_issues` | Knowledge | L1 / READ_ONLY / INTERNAL | **CONFIGURED / LOCAL OPERATIONAL** | Semantic vector search across known issue corpus. |
| `investigate_incident` | Investigation | L3 / READ_ONLY / CONFIDENTIAL | **OPERATIONAL (PARTIAL SOURCES)** | Executes exactly 4 subordinate operations. Returns structured findings. |

---

## 7. Gateway Ownership & Security Perimeter

The MCP Gateway is the sole external network ingress and security boundary.

### Gateway Owns:
- **JWT Authentication**: Validates Bearer tokens (format, expiration, claims, cryptographic signature).
- **Identity Context**: Extracts caller identity (`sub`), assigned role (`role`), and privilege flags (`production_write`, `attachment_access`).
- **YAML RBAC Policy Enforcement**: Evaluates declarative role permissions from `tool_permissions.yaml` under strict deny-by-default.
- **Privilege Flag Validation**: Enforces requirement for `production_write` and `attachment_access` flags.
- **Rate Limiting**: In-memory sliding-window rate limiting per identity and per tool.
- **Correlation ID Tracking**: Generates or validates `X-Correlation-ID` on all inbound requests.
- **Audit Logging**: Emits structured JSON audit records for all tool access attempts (allowed and denied).
- **Backend Routing**: Proxies authorized requests to backend MCP servers over Streamable HTTP.
- **Safe Global Sanitization**: Recursively scrubs recognized secrets, tokens, and PII before returning payloads to external AI clients.

### Gateway Does NOT Own:
- Business domain logic (e.g. ticket workflow calculations).
- AI reasoning or prompt engineering.
- Direct database connections or SQL queries.
- Application transformations or entity synthesis.
- JWT token issuance (tokens are minted by external identity providers).
- Durable multi-request business or user state.

---

## 8. Role-Based Access Control (RBAC) Specification

Access control is strictly declarative and enforced via `platform_security.rbac.YamlPolicyEngine` reading `tool_permissions.yaml`.

### Policy Invariants:
- **Deny-by-Default**: Access is denied unless an explicit rule allows it.
- **Unknown Entity Denial**: Unknown roles, unmapped tools, or invalid tokens are unconditionally rejected (`DENY`).

### Canonical Roles:
- **`L1` (Support Agent Tier 1)**: Basic ticket triage and technical knowledge retrieval.
- **`L2` (Support Engineer Tier 2)**: L1 capabilities plus read-only database and system diagnostics.
- **`L3` (Senior Engineer / Escalation Tier 3)**: L2 capabilities plus composite cross-system incident investigation (`investigate_incident`).

### Side-Effect Classifications:
- `READ_ONLY`: Queries without system side-effects (all 18 current registered tools are `READ_ONLY`).
- `SAFE_WRITE`: Reversible, low-risk state mutations (none registered in Local Development Release 1.0).
- `SENSITIVE_WRITE`: State mutations requiring explicit approval (none registered).
- `DESTRUCTIVE`: Non-reversible deletions or schema alterations (strictly prohibited).

### Data Classification Levels:
- `PUBLIC`: Publicly releasable documentation.
- `INTERNAL`: Internal organizational documentation and operational procedures.
- `CONFIDENTIAL`: Customer CRM data, ticket bodies, diagnostic records, and system logs.
- `RESTRICTED`: Highly sensitive operational credentials or compliance-restricted records.
- `SECRET`: Cryptographic keys, passwords, and connection credentials (never exposed).

### Specific Privileges:
- `production_write`: Flag required to execute write tools in production environments.
- `attachment_access`: Flag required to access raw attachment contents (when implemented).

### Knowledge Tool Authorization:
All three public Knowledge tools are explicitly authorized for `L1` baseline access:
- `search_knowledge`: Minimum Role: `L1` | Classification: `READ_ONLY` | Data Level: `INTERNAL`
- `get_runbook`: Minimum Role: `L1` | Classification: `READ_ONLY` | Data Level: `INTERNAL`
- `find_known_issues`: Minimum Role: `L1` | Classification: `READ_ONLY` | Data Level: `INTERNAL`

---

## 9. Attachment Security (Decision D05)

- **Status**: `RESOLVED / ENFORCED`.
- **Policy**: `DENY BY DEFAULT`.
- **Public Exposure**: The public tool inventory includes only `list_attachments`, which returns strictly **metadata** (attachment ID, filename, content type, size in bytes).
- **No Raw Content to AI**: The platform does not automatically download, parse, or feed raw attachment files (PDF, DOCX, images) to the AI model.
- **Future Pipeline**: Any future raw attachment retrieval requires explicit `attachment_access` privilege, anti-malware scanning, and DLP content inspection, and remains deferred.

---

## 10. External AI Boundary & Data Privacy (Decision D08)

- **Status**: `OPEN / ENFORCED`.
- **Policy**:
  - Live production transmission of confidential/sensitive SuperOffice CRM data to external AI model endpoints is **NOT APPROVED**.
  - Ingestion of live customer CRM exports into the Knowledge vector store is **STRICTLY DENIED**.
- **Enforcement**:
  - Local development uses synthetic sample data and mock fixtures.
  - Decision D08 cannot be marked resolved until an organizational Data Protection Impact Assessment (DPIA) and formal data classification sign-off are completed.

---

## 11. Database Diagnostics Security (Decisions D01, D02, D09)

Diagnostics against Microsoft SQL Server are strictly constrained:
- **D01 — Statement Timeout**: Mandatory hard statement query timeout of **5 seconds** (`DIAGNOSTICS_MSSQL_QUERY_TIMEOUT_SECONDS=5`). Queries exceeding 5 seconds are terminated by the database engine.
- **D02 — Result Row Ceiling**: Maximum result rows hard-capped at **50 rows** (`DIAGNOSTICS_MSSQL_MAX_ROWS=50`). Queries use `SELECT TOP (50)` or parameterized limit logic.
- **D09 — Transaction Isolation**: Mandatory **`SNAPSHOT`** isolation. Operational prerequisite: DBA must confirm `ALLOW_SNAPSHOT_ISOLATION=ON` on target database. The application does not execute DDL (`ALTER DATABASE`). No automatic `READ UNCOMMITTED` fallback.
- **Prohibitions**:
  - Zero `WITH (NOLOCK)` table hints.
  - Zero `READ UNCOMMITTED` transactions.
  - Zero arbitrary SQL execution tools.
  - Zero `SELECT *` wildcard queries; all column lists are explicitly enumerated.
  - All runtime queries use fixed, static parameterized templates.

---

## 12. Application & System Log Diagnostics

- **Tool**: `search_logs` on Diagnostics MCP.
- **Status**: `IMPLEMENTED / CONFIGURATION-CONDITIONAL`.
- **Supported Sources**:
  1. IIS W3C format access logs.
  2. SuperOffice system warning / error logs.
- **Fail-Closed Semantics**: If any enabled log source fails (e.g. missing directory, unreadable file, corrupt format), the tool **fails closed** and reports an error. There is no partial success reporting when an enabled source is unreachable.
- **Security**: No arbitrary filesystem paths or file traversals permitted. Log directories are strictly bound to configured root directories.
- **Investigation Composition**: Direct invocation of `search_logs` from the composite `investigate_incident` tool is **DEFERRED**; investigation application log evidence collector returns `BLOCKED`.

---

## 13. Knowledge Backend Specification

The Knowledge backend was designed, implemented, and verified in Phase 7:
- **Database Engine**: PostgreSQL with `pgvector` extension (version `0.8.6`).
- **Database Name**: `superoffice_ai_knowledge`.
- **Schema**: `knowledge`.
- **Relational Tables**:
  1. `knowledge.documents`: Master documentation records, category, title, source reference, version, content hash.
  2. `knowledge.chunks`: Partitioned document chunks with 384-dimensional vector embeddings and HNSW vector index.
  3. `knowledge.runbooks`: Operational runbooks, prerequisite checks, step-by-step actions, and rollback plans.
  4. `knowledge.known_issues`: Verified incident patterns, symptoms, root cause, and workarounds.
- **Embedding Provider**: `FastEmbedEmbeddingProvider` (`fastembed`).
- **Embedding Model**: `BAAI/bge-small-en-v1.5` (384-dimensional dense vector embeddings).
- **Public Tools**: 3 (`search_knowledge`, `get_runbook`, `find_known_issues`).
- **Public Ingestion**: 0 tools (no public API or MCP tool for ingestion).

---

## 14. Knowledge Ingestion Pipeline & Operator CLI

Ingestion is handled exclusively via an internal offline operator CLI (`src/servers/knowledge/src/kb_mcp/ingestion/cli.py`, module execution: `python -m kb_mcp.ingestion.cli`):
```text
Operator Source File
        │
        ▼
[Admission Gate] ─── (Rejects unsupported extensions, file size > 2 MiB)
        │
        ▼
[Security Boundary] ─── (Deterministic scanning for secrets, API keys, mass PII)
        │
        ▼
[Canonical Identity Builder] ─── (Computes document_id, content_hash SHA-256)
        │
        ▼
[Deterministic Chunker] ─── (Header-aware Markdown / Structured chunking)
        │
        ▼
[Local FastEmbed Engine] ─── (Local cached BAAI/bge-small-en-v1.5 model)
        │
        ▼
[Immutable Artifact Storage] ─── (Writes approved/<type>/<id>/<hash>.md)
        │
        ▼
[Transactional PostgreSQL Engine] ─── (pg_advisory_xact_lock, atomic upsert)
```

### CLI Commands:
- `dry-run`: Validates admission, sanitization, canonical identity, and chunking without connecting to PostgreSQL, without acquiring locks, without generating embeddings, and without modifying artifacts or database tables.
- `ingest`: Executes the full transactional ingestion chain.

### Supported Local-v1 Formats:
- General Documentation: `.md`, `.markdown`, `.txt`.
- Structured Operational Data: Runbook `.json`, Known-Issue `.json`.

### Unsupported Formats (Deferred):
- YAML (`.yaml`, `.yml`), PDF (`.pdf`), Word (`.docx`), HTML (`.html`), Scanned Images / OCR.

---

## 15. Knowledge Artifact Layout & Storage Engine

### FLC.2 Reconciliation Correction:
Approved Knowledge artifacts are **NOT JSON files**. The implemented 7D.5C approved artifact layout stores sanitized canonical content as Markdown:
```text
approved/<document_type>/<document_id>/<content_hash>.md
```

### Artifact Characteristics:
- **Content-Addressed**: Keyed by SHA-256 hash of the canonical content.
- **Immutable & Non-Overwriting**: If an artifact with the same hash exists, it is preserved.
- **Outside Git**: Artifact storage resides on the local filesystem outside source control.
- **Sanitized Canonical Content**: Contains pre-redacted text safe for operational retrieval.

### Consistency & Reconciliation:
- **Artifact Existence ≠ Active Knowledge**: An artifact written to the filesystem does not make it visible to vector search. Visibility requires a committed PostgreSQL transaction.
- **No Distributed 2PC**: The local filesystem and PostgreSQL do not share a two-phase commit coordinator.
- **Compensation & Reconciliation**: If database persistence fails after artifact creation, the uncommitted artifact remains orphaned but harmless, and is flagged for reconciliation.

---

## 16. Knowledge Concurrency & Versioning Control

- **Concurrency Control**: Protected by PostgreSQL transaction-scoped advisory locks:
  ```sql
  SELECT pg_advisory_xact_lock(hashtext('knowledge_document:' || $1));
  ```
- **Scope**: Ingestion operations for the same `document_id` are strictly serialized.
- **Inference Optimization**: Expensive embedding model inference (`FastEmbed`) is computed **before** acquiring the advisory lock, minimizing lock hold time.
- **Versioning Invariant**:
  - New document: `version = 1`.
  - Unchanged content (`content_hash` match): `version` remains unchanged (`status = UNCHANGED`).
  - Modified content: `version = version + 1` (`status = UPDATED`).
- **Atomic Chunk Replacement**: In a single database transaction, existing chunks are deleted and replaced with new embedding chunks.

---

## 17. Incident Investigation MCP Service (`investigation-mcp`)

The `investigation-mcp` service is a dedicated microservice hosting the public `investigate_incident` composite tool over Streamable HTTP (port 8005).

### Subordinate Composition:
The composite tool executes **exactly 4 frozen physical subordinate operations** via internal Streamable HTTP adapters:
1. `get_ticket` (SuperOffice MCP)
2. `get_database_health` (Diagnostics MCP)
3. `find_slow_queries` (Diagnostics MCP)
4. `find_deadlocks` (Diagnostics MCP)

### Prohibited Operations:
- No calls to `search_tickets` or `find_blocking_sessions`.
- No calls to `search_logs`.
- No calls to `Knowledge` MCP tools.

### Current Subordinate Evidence Outcomes:
- `application_logs`: Returns `EvidenceOutcome.BLOCKED` (zero synthetic or fabricated log records).
- `knowledge_base`: Returns `EvidenceOutcome.NOT_CONFIGURED` (zero synthetic or fabricated runbook records).

---

## 18. Infrastructure MCP Server Boundary

- **Public Tools**: **0 public tools**.
- **Status**: Structural server slot retained (`TargetServer.INFRASTRUCTURE`); detailed probe capabilities are **DEFERRED** under Decision `D07`.
- **Candidate Future Probes**: Host metrics (CPU, memory, disk), IIS application pool status, Windows service status.
- **Prohibitions**:
  - Zero arbitrary shell execution capabilities.
  - Zero general filesystem access or file manipulation.
  - Zero raw network scanning or socket probing tools.

---

## 19. Transport Architecture & Verified Local Ports

- **Transport**: **Streamable HTTP** is mandatory across all MCP runtimes (ADR 007).
- **Runtimes**: Stateless FastMCP / Streamable HTTP session managers.
- **Official SDK**: Built exclusively using the official Python MCP SDK (`mcp`). No custom transport wrappers.
- **Verified Default Local Ports**:
  - **Gateway**: `8000`
  - **SuperOffice MCP**: `8001`
  - **Diagnostics MCP**: `8002`
  - **Knowledge MCP**: `8003`
  - **Infrastructure MCP**: `8004`
  - **Investigation MCP**: `8005`

---

## 20. Local-Development-Only Exceptions

The following configuration choices are approved **strictly for local development and offline testing**, and must be replaced during production deployment:

1. **SuperOffice Self-Signed TLS Trust Exception**:
   - Setting: `SUPEROFFICE_ALLOW_SELF_SIGNED_CERT=true`.
   - Local: Bypasses strict CA validation for local testing against mock/test servers.
   - Production: Must be `false`; valid enterprise CA certificate required.
2. **MSSQL Certificate Trust Exception**:
   - Setting: `DIAGNOSTICS_MSSQL_TRUST_SERVER_CERTIFICATE=true`.
   - Local: Connects to local development SQL Server instances with self-signed certificates.
   - Production: Must be `false`; validated enterprise TLS trust required.
3. **HS256 Local JWT Verification / Signing**:
   - Local: Uses symmetric HMAC-SHA256 (`HS256`) shared secret for test token generation and verification.
   - Production: Asymmetric key validation via enterprise Identity Provider JWKS (algorithm TBD during Production Readiness Program).
4. **Localhost PostgreSQL Database**:
   - Local: Connects to `127.0.0.1:5432/superoffice_ai_knowledge`.
   - Production: Dedicated managed cluster with high availability and automated backup.
5. **Local Filesystem Artifact Root**:
   - Local: Stores approved `.md` Knowledge artifacts in a local filesystem directory.
   - Production: Durable artifact storage architecture is **TBD DURING PRODUCTION READINESS PROGRAM** (technologies like S3, Azure Blob, GCS, or MinIO are not prematurely selected).
6. **Local FastEmbed Cached Model**:
   - Local: Embeddings run in-process using locally cached model weights.
   - Production: Scaled inference architecture to be assessed during production readiness.

---

## 21. Authoritative Architecture Decision Ledger (D01–D09)

| Decision ID | Area | Subject | Status | Resolution / Frozen Invariants |
| :--- | :--- | :--- | :--- | :--- |
| **D01** | Diagnostics MSSQL | Statement Query Timeout | **RESOLVED** | **5.0 seconds** (`DIAGNOSTICS_MSSQL_QUERY_TIMEOUT_SECONDS=5`). Hard query cancellation safety ceiling. |
| **D02** | Diagnostics MSSQL | Maximum Result Rows | **RESOLVED** | **50 rows** (`DIAGNOSTICS_MSSQL_MAX_ROWS=50`). Hard safety ceiling enforced at query compile & runtime limit. |
| **D03** | Gateway Security | Declarative Tool-Level RBAC | **RESOLVED** | Declarative YAML-based RBAC (`tool_permissions.yaml`) loaded at startup by Gateway. Enforces deny-by-default. |
| **D04** | SuperOffice Integration | Attachment MD5 Metadata | **OPEN / NON-BLOCKING** | Discrepancy between SuperOffice REST API metadata and local MD5 expectations remains open. Runtime behavior: `md5_hash=None`. Non-blocking. |
| **D05** | Attachment Security | Attachment Authorization & Access | **RESOLVED / ENFORCED** | **Deny-by-default**. Public tool `list_attachments` returns metadata only. No raw attachment content exposed to AI. |
| **D06** | Observability | stdout/stderr Documentation | **NON-BLOCKING** | Minor documentation discrepancy regarding stream destinations; runtime structured logging behavior is unchanged. |
| **D07** | Infrastructure | Infrastructure Adapter Contracts | **DEFERRED** | Infrastructure detailed adapter contracts remain deferred. Server retained with 0 public tools. |
| **D08** | External AI Boundary | Production Sensitive CRM Boundary | **OPEN / ENFORCED** | Live production transmission of sensitive CRM data to external AI is **NOT APPROVED**. Knowledge ingestion of live customer CRM exports is **DENIED**. |
| **D09** | Diagnostics MSSQL | Transaction Isolation | **RESOLVED / APPROVED** | **SNAPSHOT** isolation mandatory. Operational prerequisite: DBA must enable `ALLOW_SNAPSHOT_ISOLATION=ON`. Zero `NOLOCK` hints. |

---

## 22. Authoritative Deferred & Blocked Items Inventory

| Item / Capability | Status | Reason / Dependency | Target Future Phase |
| :--- | :--- | :--- | :--- |
| **D04 Attachment MD5 Discrepancy** | `OPEN / NON-BLOCKING` | SuperOffice API does not provide pre-computed MD5 hashes in file metadata | Operational Review |
| **D07 Infrastructure Adapter Contracts** | `DEFERRED` | Host security policy and probe safety boundaries not yet established | PR.1 / PR.4 |
| **D08 External AI Live CRM Boundary** | `OPEN / ENFORCED` | Requires organizational Data Protection Impact Assessment (DPIA) & compliance sign-off | PR.3 / PR.10 |
| **Investigation → `search_logs` Integration** | `DEFERRED` | Application log collection requires safe correlation key indexing | PR.6 |
| **Investigation → `Knowledge` Integration** | `NOT_CONFIGURED / DEFERRED` | Automatic RAG injection into incident investigation requires tuning | Post-Release 1.0 |
| **`get_ticket_diagnostic_record` Tool** | `BLOCKED` | Database table/view names and foreign key relationships unverified by DBA | Schema Verification |
| **Production Deployment & Network Trust** | `NOT STARTED` | Production topology, service isolation, network policy, and service-to-service trust mechanisms have not yet been selected and validated | PR.0 / PR.1 / PR.3 / PR.4 |
| **Remote Diagnostics Agent Placement** | `NOT STARTED` | Multi-host or remote agent topology requires network boundary evaluation | PR.1 |
| **Infrastructure MCP Tool Implementation** | `DEFERRED` | Detailed host OS probe capabilities deferred under D07 | PR.1 / PR.2 |
| **Knowledge Ingestion: PDF / DOCX / HTML / OCR** | `DEFERRED` | Local v1 supports Markdown, Text, and structured JSON only | Post-Release 1.0 |
| **Knowledge Ingestion: YAML Sources** | `DEFERRED` | Structured schema validation deferred for non-JSON formats | Post-Release 1.0 |

---

## 23. What Local Development Release 1.0 Does NOT Claim

To prevent any misunderstanding of the platform's operational readiness, the following boundaries are explicitly declared:

> [!WARNING]
> **Production Boundary Disclaimer**
> 
> **Local Development Release 1.0 DOES NOT CLAIM:**
> 1. **Production Deployment**: The platform is not deployed to production environments.
> 2. **Production Network Trust**: Production topology, network policy, and service isolation controls are not yet selected or validated.
> 3. **Production Service-to-Service Cryptographic Trust**: Second-hop identity is passed via internal transport context; production service-to-service trust mechanisms are not yet selected.
> 4. **High Availability (HA)**: No multi-instance redundancy, active-active failover, or leader election is claimed.
> 5. **Disaster Recovery (DR)**: No automated disaster recovery failover is configured.
> 6. **Backup / Restore Validation**: PostgreSQL and MSSQL automated backup/restore procedures have not been validated in a production operational drill.
> 7. **Production Observability / SLO Acceptance**: Production APM agents, Prometheus scraping endpoints, alerting rules, and SLO dashboards are not provisioned.
> 8. **Production Secrets Management**: No integration with HashiCorp Vault, AWS Secrets Manager, or Azure Key Vault is implemented.
> 9. **Production CI/CD Promotion**: Automated multi-environment release promotion pipelines are not configured.
> 10. **Decision D08 Resolution**: Confidential live CRM data transmission to external AI endpoints remains unapproved.
> 11. **Infrastructure MCP Tools**: Host diagnostic capabilities remain at 0 public tools.

---

## 24. Future Roadmap

Following the completion of Local Development Release 1.0, the project will progress through the following planned stages:

### Immediate Local Release Track
- **FLC.4 — Local Development Release 1.0 Checkpoint & Tag** (`COMPLETE / APPROVED`): Formal repository tag (`v1.0.0-local.1`) and baseline lock.
- **FLC.5 — Repository Professionalization & Remote Publication** (`NOT STARTED`):
  - Repository cleanup, Git history secret audit, README polish.
  - License determination, `SECURITY.md`, `CONTRIBUTING.md`, `CODEOWNERS`.
  - CI workflow definition.
  - Controlled initial remote push to private repository.

### Production Readiness Program (Roadmap — All Future / Not Started)
- **PR.0 — Production Readiness Assessment**: Architecture gap analysis against production enterprise standards.
- **PR.1 — Production Deployment Architecture**: Container topology, host placement, and ingress design.
- **PR.2 — Runtime Packaging & Containerization**: Hardened Docker images, non-root user execution, minimal base images.
- **PR.3 — Production Security, Secrets & PKI**: Enterprise secret store integration and PKI lifecycle.
- **PR.4 — Network Trust & Service Isolation**: Network topology, service isolation boundaries, network policies, and service-to-service cryptographic trust validation.
- **PR.5 — Production Data, Backup & Recovery**: Managed database provisioning, point-in-time recovery, vector index maintenance.
- **PR.6 — Observability, Monitoring & Alerting**: Distributed tracing (OpenTelemetry), metrics collection, and alerting thresholds.
- **PR.7 — CI/CD & Release Promotion**: Automated build, test, container scan, and staged promotion pipelines.
- **PR.8 — High Availability & Resilience**: Horizontal scaling, connection pool sizing, circuit breaker tuning.
- **PR.9 — Performance, Load & Failure Testing**: Benchmarking under concurrent load, chaos testing, timeout validation.
- **PR.10 — Security Validation & Penetration Testing**: External vulnerability scanning, penetration testing, DPIA completion for D08.
- **PR.11 — Operational Runbooks & Support**: Production operations runbooks, disaster recovery drills, on-call documentation.
- **PR.12 — Production Acceptance**: Formal operational handover and production sign-off.

---

## 25. Verified Quality & Testing Baseline

The local platform has been comprehensively verified and validated across all unit, integration, and security test suites:

- **Full Platform Regression Suite**:
  - **Passed**: `1043` tests
  - **Skipped**: `11` tests (opt-in live database mutation tests guarded by environment variables)
  - **Failed**: `0`
- **Focused Security & Contract Suite (FLC.2)**:
  - **Passed**: `396` tests (100% pass rate)
- **Code Quality & Static Analysis**:
  - **Ruff (Linter)**: `PASS` (0 errors across `src/` and `tests/`)
  - **Ruff (Formatter)**: `PASS` (100% formatted)
  - **Mypy (Strict Static Type Checker)**: `PASS` (0 issues across all modules)

---

## 26. Controlled Local Knowledge Sample Corpus

The local Knowledge test database (`superoffice_ai_knowledge`) is populated with a strictly controlled, synthetic sample corpus for local verification:
- **Documents**: `3` synthetic technical documents.
- **Chunks**: `6` embedding chunks (indexed with `BAAI/bge-small-en-v1.5` embeddings).
- **Runbooks**: `3` synthetic operational troubleshooting runbooks.
- **Known Issues**: `3` synthetic known issue records.
- **Data Privacy**: Zero customer data, zero production CRM extracts, and zero real credentials.
