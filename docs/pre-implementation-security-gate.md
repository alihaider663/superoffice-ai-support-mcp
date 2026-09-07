# Pre-Implementation Security Gate

## SuperOffice AI Support MCP Platform — Phase 0.6

**Date**: 2026-08-29  
**Status**: Formal Pre-Implementation Security Gate Complete  
**Governance Scope**: Mandatory Pre-Requisite for Phase 1 Scaffolding

---

## 1. Security Boundary & Gateway Architecture

### 1.1 The AI Model is NOT a Security Boundary
The core security axiom of this platform is that **the AI agent is completely untrusted from a security and access-control perspective**. The AI model cannot be relied upon to restrict its own data access, self-redact sensitive PII, respect tenant boundaries, or abstain from destructive actions. 

All security policies, authentication checks, tool-level authorizations, data minimization transformations, and output sanitizations are enforced strictly in **deterministic, deterministic application and gateway code** prior to exposing any payload to the model.

### 1.2 End-to-End Request & Data Flow
Every interaction between the AI agent and the enterprise environment follows a strictly unidirectional pipeline with ingress and egress security gates:

```text
AI Agent
   │  (Streamable HTTP + JWT Bearer)
   ▼
MCP Gateway (Security Boundary)
   │
   ├── 1. Authentication (Signature, Expiry, Issuer, Audience, Claims)
   ├── 2. Authorization (Role vs. tool_permissions.yaml minimum_role)
   ├── 3. Privilege Checks (production_write, attachment_access)
   ├── 4. Rate Limiting & Abuse Prevention
   ├── 5. Audit Log Ingress (Identity, Tool, Correlation ID, Timestamp)
   │
   ▼ (Proxy via httpx to internal MCP Server)
MCP Server (SuperOffice | Diagnostics | Knowledge | Infrastructure)
   │
   ▼
Application Services (Business Layer)
   │  ├── Purpose-based field selection
   │  ├── PII Masking & Data Minimization
   │  └── Strict typed input validation (Pydantic)
   │
   ▼
Integration Clients (Isolated Adapters)
   │  ├── Parameterized queries / API calls
   │  ├── Connection pooling & Query timeouts
   │  └── Read-only credentials by default
   │
   ▼
Backend Enterprise Systems (SuperOffice APIs | MSSQL | Supabase | Infrastructure)
   │
   ▼ (Filtered Result Payload)
Integration Clients → Application Services
   │
   ▼
MCP Server Response
   │
   ▼
MCP Gateway (Egress Security Gate)
   │  ├── Output Security & PII/Secret Sanitization
   │  ├── Exception Sanitization (No stack traces / credentials)
   │  └── Audit Log Egress (Result status, duration, payload metadata)
   │
   ▼ (Sanitized Minimal Response)
AI Agent
```

### 1.3 Strict Gateway Responsibilities
The MCP Gateway acts exclusively as the security, policy, and routing perimeter.

#### Gateway OWNS:
* Ingress authentication and token validation (JWT).
* Identity context extraction and propagation (`sub`, `role`, `permissions`).
* Deterministic RBAC enforcement via `tool_permissions.yaml`.
* Privilege flag validation (`production_write`, `attachment_access`).
* Request structure and schema validation.
* Rate limiting and per-identity throttling.
* Centralized audit logging and correlation ID tracking.
* Global exception handling and error sanitization.
* Response filtering and egress secret protection.

#### Gateway DOES NOT OWN:
* SuperOffice business logic or entity lifecycle management.
* MSSQL query generation or database diagnostic logic.
* RAG retrieval, vector search, or knowledge ranking.
* Infrastructure metric collection or server health probing.
* Direct connections to SuperOffice APIs, MSSQL, Supabase, or production hosts.
* AI reasoning or prompt orchestration.

---

## 2. Authentication (JWT Security)

In accordance with [ADR 009](adr/009-jwt-authentication.md), authentication is enforced at the Gateway on every HTTP request.

### 2.1 Token Validation Requirements
The Gateway must execute the following validation steps sequentially before evaluating tool permissions:
1. **Transport Header Extraction**: Verify the `Authorization: Bearer <token>` header is present and well-formed.
2. **Signature Verification**: Validate cryptographic signature against the active signing key or JWKS endpoint.
3. **Expiration Enforcement (`exp`)**: Reject any expired token with a strict expiration window (recommended: 1-hour max lifespan).
4. **Not-Before / Issued-At Enforcement (`nbf`, `iat`)**: Reject tokens with invalid timestamps, permitting a maximum clock skew tolerance of 60 seconds.
5. **Issuer Validation (`iss`)**: Enforce matching issuer string (e.g., `superoffice-ai-support`).
6. **Audience Validation (`aud`)**: Enforce matching audience string (`mcp-gateway`).
7. **Required Claims Extraction**: Validate presence of `sub` (identity string) and `role` (`L1` | `L2` | `L3`).

### 2.2 Environment Separation
* **Development (`APP_ENV=development`)**:
  * May use symmetric HMAC (HS256) with a development signing secret configured in `.env`.
  * Allows rapid local development and automated testing fixtures without requiring PKI infrastructure.
* **Production (`APP_ENV=production`)**:
  * Must use asymmetric keys (RS256 or ES256) or an enterprise JWKS (JSON Web Key Set) endpoint.
  * The Gateway only possesses the public verification key / certificate, eliminating the risk of token forgery if the Gateway container is compromised.

---

## 3. Authorization & RBAC Controls

In accordance with [ADR 010](adr/010-yaml-rbac-configuration.md), all tool executions are governed by declarative YAML configuration (`tool_permissions.yaml`) loaded and validated at Gateway startup.

### 3.1 Strict Deny-by-Default
* Any tool invoked by the AI agent that is not explicitly defined in `tool_permissions.yaml` is **immediately rejected with 403 Forbidden**.
* Unauthenticated requests are rejected with **401 Unauthorized**.

### 3.2 Cumulative Role Hierarchy & Minimum Role Assignment
The role hierarchy is strictly ordered: `L1 < L2 < L3`.

```text
┌─────────────────────────────────────────────────────────────┐
│ L3 (Advanced Technical Investigation)                       │
│  ├── Infrastructure MCP (CPU, Memory, Disk, Services, LB)   │
│  ├── Advanced DB Diagnostics (Deadlocks, Blocking Sessions) │
│  ├── Attachment Content Access (Requires explicit flag)     │
│  └──────────────────────────┬───────────────────────────────┘
│                             │ (inherits all L2)
│                             ▼
│ ┌─────────────────────────────────────────────────────────┐
│ │ L2 (Extended Technical Investigation)                   │
│ │  ├── Application Logs & API Error Search                │
│ │  ├── Standard DB Diagnostics (Slow Queries, Indexes)    │
│ │  ├── Customer / Person Entity Details                   │
│ │  ├── Transaction Correlation                            │
│ │  └────────────────────────┬─────────────────────────────┘
│                             │ (inherits all L1)
│                             ▼
│ ┌───────────────────────────────────────────────────────┐
│ │ L1 (Basic Ticket Investigation)                       │
│ │  ├── Ticket Summary, Status, Public Events            │
│ │  ├── Attachment Metadata (Filename, Size, Type)       │
│ │  └── Knowledge Search & Standard Runbook Retrieval    │
│ └───────────────────────────────────────────────────────┘
```

### 3.3 Critical Rule: L3 is NOT Unrestricted Access
* **`L3 ≠ Unrestricted Access`**: An L3 identity does **not** have blanket permission to execute arbitrary code, arbitrary SQL, destructive writes, or bypass data filtering.
* L3 only unlocks specifically enumerated diagnostic and infrastructure tools defined in the configuration schema.
* Production writes and attachment content access remain gated behind separate orthogonal privilege flags.

### 3.4 Orthogonal Privilege Separation
1. **`production_write`**:
   * Modifying ticket status, posting notes, or submitting customer replies requires the tool classification `SAFE_WRITE` or `SENSITIVE_WRITE` AND the JWT claim `production_write: true`.
   * An L2 or L3 user without `production_write: true` is strictly read-only.
2. **`attachment_access`**:
   * Accessing raw or processed attachment content requires `minimum_role: L3`, the tool definition requirement `requires: [attachment_access]`, the JWT claim `attachment_access: true`, AND the runtime setting `ATTACHMENT_ACCESS_ENABLED=true`.

---

## 4. SuperOffice Customer Data Protection

SuperOffice is the primary business repository containing customer records, confidential correspondence, and sensitive business data.

### 4.1 Data Minimization Principles
* **Identifier / Metadata First**: Investigation workflows must prioritize ticket IDs, entity IDs, timestamps, status strings, and system category codes before requesting descriptive text.
* **Field-Level Projection**: MCP tools and Application Services must explicitly project only required fields. Database queries and REST API requests must not use wildcard selectors (`SELECT *` or raw unbounded entity JSON dumping).
* **Summary over Raw Text**: When ticket descriptions or conversation threads are retrieved, application services should return truncated summaries or key excerpts rather than multi-year historical thread dumps.

### 4.2 PII Protection & Scrubbing
* Direct customer identifiers (national identification numbers, credit card details, passwords, personal addresses, personal phone numbers) must be masked or scrubbed by application services before reaching the Gateway.
* Customer email addresses and contact names are classified as **Level 3 — Restricted** and are restricted to L2/L3 roles with explicit redaction applied where not directly relevant to the incident.

---

## 5. Attachment Protection & Future Inspection Pipeline

In accordance with [ADR 003](adr/003-attachment-security.md) and [docs/data-classification.md](data-classification.md), all attachments (PDF, PNG, JPG, DOCX, XLSX, TXT, screenshots, ZIPs) are classified as **Level 3 — Restricted** and are **DENY by default**.

### 5.1 Metadata vs. Content Separation
* **`list_attachments` / `get_attachment_metadata`**:
  * Permitted at **L1**.
  * Returns strictly non-sensitive file metadata: `attachment_id`, `filename`, `content_type`, `size_bytes`, `created_at`.
  * Exposes zero byte content and zero text extraction to the AI context.
* **`get_attachment_content`**:
  * Strictly restricted to **L3** + `attachment_access` privilege.
  * Default configuration is `ATTACHMENT_ACCESS_ENABLED=false`.

### 5.2 Mandatory Attachment Processing Pipeline
When attachment content access is enabled and authorized in future phases, the raw file must traverse the multi-stage security pipeline before any content enters the AI context:

```text
Raw Attachment (Binary Store)
      │
      ▼
1. Authorization Gate (RBAC L3 + attachment_access flag verification)
      │
      ▼
2. Purpose & Policy Check (Allowlisted MIME types: PDF, PNG, JPG; size <= 10MB)
      │
      ▼
3. Security Inspection (Antivirus / Malware / Macro scanning)
      │
      ▼
4. Structural Text/OCR Extraction (Safe text parser, No executable execution)
      │
      ▼
5. DLP & PII Scrubbing (Regex/Entity scanning for credentials, credit cards, PII)
      │
      ▼
6. Content Minimization & Redaction (Extract only relevant error snippet / log table)
      │
      ▼
Approved Text Excerpt → AI Agent Context
```

* Raw binary files (images, PDFs) are **never directly injected into LLM context windows**.
* Every attachment access request produces an immutable audit record containing `attachment_id`, `requested_by`, `role`, and `authorization_decision`.

---

## 6. MSSQL Database Protection & Diagnostic Boundaries

MSSQL is used exclusively for SuperOffice database diagnostics. It is accessed solely via the Diagnostics MCP and Application Services layer.

### 6.1 Strict Prohibition of Arbitrary SQL
* Under no circumstances shall an MCP tool accept raw SQL query strings (e.g., `execute_sql(query: str)` or `run_query(...)`).
* All database interactions are encapsulated into fixed, purpose-built, parameterized diagnostic tools:
  * `find_slow_queries(time_window_minutes, min_duration_ms)`
  * `find_deadlocks(time_window_minutes)`
  * `find_blocking_sessions()`
  * `get_database_health()`
  * `get_ticket_diagnostics(ticket_id)`

### 6.2 Connection & Operational Safeguards
1. **Read-Only Credentials**: The MSSQL database user configured in `.env` (`DATABASE_USER`) must have strictly read-only permissions (`db_datareader` or explicit `SELECT` grants on specific diagnostic views/DMVs like `sys.dm_exec_requests`, `sys.dm_exec_query_stats`). DDL and DML write permissions (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`) must be prohibited at the database role level.
2. **Parameterized Queries**: All queries must utilize strictly parameterized inputs via standard database drivers. String concatenation or formatting of query strings is forbidden.
3. **Mandatory Query Timeouts**: Every database query must enforce an explicit client-side and server-side command timeout (default: 5.0 seconds).
4. **Hard Limit on Result Sets**: Diagnostic tools must enforce hard caps on returned rows (e.g., `TOP 50` or `LIMIT 50`) to prevent memory exhaustion and token flooding.
5. **Connection Pooling**: Database connections must be managed via a bounded connection pool with strict per-instance connection limits (e.g., max 10 connections per container) to protect database availability.

---

## 7. Supabase & Knowledge Base Protection

Supabase (PostgreSQL + pgvector) serves as the persistent retrieval engine behind the Knowledge MCP. It is **not** a general data store for customer data.

### 7.1 Architectural Isolation
```text
AI Agent ──(HTTP)──> MCP Gateway ──(HTTP)──> Knowledge MCP ──> Application Service ──> Supabase / pgvector
                                                                                            ▲
                                                [Direct AI Access is FORBIDDEN] ────────────┘
```
* The AI agent has no network access, database credentials, or protocol access to Supabase.
* Supabase is accessible only to the Knowledge MCP application service.

### 7.2 Strict Knowledge Base Data Ingestion Boundaries
The Supabase vector store and knowledge tables must contain exclusively sanitized organizational documentation:
* **Allowed Content**:
  * Official SuperOffice administration guides and technical manuals.
  * Standard Operating Procedures (SOPs) and troubleshooting runbooks.
  * Verified known issue articles and bug workarounds.
  * Fully anonymized and sanitized historical incident resolution patterns.
* **Explicitly Forbidden Content**:
  * Live customer records, company directories, or contact tables.
  * Unsanitized production ticket dumps.
  * Production database backups or table exports.
  * Customer-provided attachment files.
  * API tokens, credentials, or connection strings.

---

## 8. Secret Protection & Credential Isolation

In accordance with [.agents/rules/security.md](../.agents/rules/security.md), credentials and secrets must be isolated from code, logs, tool payloads, and model context.

### 8.1 Zero-Secrets-in-Code Policy
* No passwords, API keys, OAuth client secrets, private keys, database connection strings, or JWT signing keys shall ever be committed to git.
* `.gitignore` explicitly excludes `.env`, `.env.*`, `*.pem`, `*.key`, `*.pfx`, `customer-data/`, `production-data/`, and `attachments/`.
* `.env.example` contains only non-sensitive configuration keys with empty values and standard comment headers.

### 8.2 Runtime Secret Isolation
* Credentials loaded from environment variables are consumed exclusively by Integration Clients inside their specific backend adapters.
* Secrets are never stored on request state objects, never passed through MCP tool arguments, and never returned in MCP tool response models.

---

## 9. Output Security & Response Sanitization

Every payload returned by an MCP server is inspected and sanitized at the Gateway egress layer before being dispatched to the AI agent.

### 9.1 Global Exception Sanitizer
* Unhandled exceptions, network errors, and database connection failures must be intercepted by a centralized Gateway exception handler.
* **Sanitized Error Schema**:
  ```json
  {
    "error": "upstream_error",
    "message": "The diagnostic service timed out while querying the database.",
    "correlation_id": "corr-98f2-4b21-817a",
    "timestamp": "2026-08-29T00:08:00Z"
  }
  ```
* **Prohibited in Error Responses**: Raw Python stack traces, file paths, database hostnames/IPs, connection string fragments, and internal driver error codes.

### 9.2 Data Scrubbing Filters
Prior to serializing tool outputs to JSON, an egress filter scrubs:
* Strings matching common API key, token, or private key patterns (e.g., `Bearer ey...`, `ghp_...`, `-----BEGIN PRIVATE KEY-----`).
* Password and secret fields in diagnostic records.
* Excessively verbose log blocks that exceed safe token boundaries.

---

## 10. Audit Logging & Compliance

In accordance with [docs/security-model.md](security-model.md), every operation passing through the MCP Gateway generates an immutable, structured audit event.

### 10.1 Required Audit Event Fields
```json
{
  "event_id": "evt-771a-45c0",
  "correlation_id": "corr-98f2-4b21-817a",
  "timestamp": "2026-08-29T00:08:00.124Z",
  "identity": "support-agent-01",
  "role": "L2",
  "mcp_server": "diagnostics-mcp",
  "tool_name": "find_slow_queries",
  "authorization_result": "GRANTED",
  "execution_status": "SUCCESS",
  "duration_ms": 48.2,
  "request_params": {
    "time_window_minutes": 15,
    "min_duration_ms": 1000
  },
  "response_metadata": {
    "row_count": 3,
    "payload_bytes": 1420
  }
}
```

### 10.2 Explicit Prohibition on Audit Payload Contents
To prevent audit logs from becoming a secondary vector for data leaks, audit logging **must never capture**:
* Passwords, secrets, or bearer tokens.
* Full binary contents of attachments.
* Sensitive customer correspondence or unredacted PII bodies.
* Database connection strings.

---

## 11. Remaining Architecture Risks Assessment & Disposition

| Risk Identifier | Description | Current Severity | Disposition | Resolution Plan |
|---|---|---|---|---|
| **R1: Gateway SPOF** | Central Gateway is single point of failure | HIGH | **Addressed Architecturally** | Gateway is completely stateless (ADR 008). Multiple instances run behind standard HTTP load balancers in production. |
| **R2: DB Pool Exhaustion** | Multiple stateless MCP instances exhaust MSSQL connections | HIGH | **Deferred to Implementation** | Phase 1 will implement strict per-instance connection pool caps and query timeouts in the MSSQL integration client. |
| **R3: Incomplete PII Scrubbing** | PII embedded in unstructured log text or error dumps | HIGH | **Addressed Architecturally & Implementation** | Layered scrubbing: (1) structured field minimization in app services, (2) regex-based PII scrubber in egress gateway filter. |
| **R4: Rate Limiting Policy** | Absence of concrete throttling thresholds | MEDIUM | **Deferred to Implementation** | Gateway implementation will include an in-memory token bucket / sliding window rate limiter per identity and per tool. |
| **R5: Binary Attachment DLP** | Parsing and scrubbing text in PDF/PNG/images | MEDIUM | **Deferred to Production Hardening** | Attachments are hard-disabled (`ATTACHMENT_ACCESS_ENABLED=false`). Future enablement requires dedicated scanning microservice. |
| **R6: Audit Log Volume** | High log volume under heavy concurrent investigations | LOW | **Deferred to Production Hardening** | Structured JSON logging to `stdout` in Phase 1; external log ingestion (ELK/CloudWatch/Splunk) configured in production topology. |

---

## 12. Phase 1 Implementation Prerequisites Checklist

Before executing any application code, database connectors, or MCP server implementations in Phase 1, the following foundational controls must be in place:

- [x] **Architecture Baselined**: ADRs 001–010 fully documented, cross-referenced, and accepted.
- [x] **Scope Frozen**: Zero references to excluded systems (WSO2, Automic/UC4/UC8); verified single-domain focus on SuperOffice.
- [x] **Security Model Approved**: Deny-by-default, L1/L2/L3 role hierarchy, orthogonal privileges, and data classification confirmed.
- [ ] **Phase 1 Scaffolding Plan Approved**: Implementation plan created for project directory structure, dependency definitions (`pyproject.toml` with `uv`), and core test harness.
- [ ] **Configuration Model Ready**: Pydantic settings schema drafted to strictly parse `.env` configuration without defaulting sensitive features to `true`.
- [ ] **Mock Test Strategy Defined**: Comprehensive mock suite designed for SuperOffice API, MSSQL, and Supabase integration clients to ensure zero production connections during development and testing.

---

## Conclusion & Gate Sign-Off

The architecture, security boundaries, and data governance policies of the SuperOffice AI Support MCP Platform have been rigorously reviewed and confirmed. The platform design prevents unauthorized data exposure, protects customer confidentiality, and strictly isolates backend infrastructure from direct AI manipulation.

**Phase 0.6 Pre-Implementation Security Gate is PASSED.**
