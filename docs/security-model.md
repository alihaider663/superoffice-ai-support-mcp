# SuperOffice AI Support MCP Platform — Security Model

## 1. Security Objective

The SuperOffice AI Support MCP Platform provides AI-assisted troubleshooting without exposing confidential enterprise or customer data to external AI models.

**Core Invariant**: Security is strictly enforced by deterministic, verified application code. The AI model is **never** considered a security boundary.

---

## 2. Defense in Depth

Security controls are applied at multiple sequential layers:

```text
External Client Request
        ↓
[ 1. Transport Security ] ─── (Streamable HTTP, Host Header / DNS Rebinding Guard)
        ↓
[ 2. Authentication ] ─── (JWT Bearer Token Signature & Claims Validation)
        ↓
[ 3. Authorization & RBAC ] ─── (Declarative YAML Policy: L1/L2/L3, Deny-by-Default)
        ↓
[ 4. Privilege Verification ] ─── (Explicit production_write / attachment_access Flags)
        ↓
[ 5. Rate Limiting ] ─── (Sliding-Window Per-Caller & Per-Tool Throttling)
        ↓
[ 6. Data Classification ] ─── (PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED, SECRET)
        ↓
[ 7. Domain Constraints ] ─── (D01: 5s Query Timeout, D02: 50-Row Ceiling, D09: SNAPSHOT)
        ↓
[ 8. Attachment Policy ] ─── (Decision D05: Deny-by-Default, Metadata Only)
        ↓
[ 9. Data Minimization & Redaction ] ─── (Recursive Secret & PII Scrubbing)
        ↓
[ 10. Audit Logging ] ─── (Structured JSON Audit Sink with Correlation ID)
        ↓
AI Reasoning Context
```

---

## 3. Perimeter Authentication & Token Processing

- **Perimeter Enforcement**: All external access terminates at the **MCP Gateway** (`platform-gateway`, port 8000).
- **Token Format**: Standard RFC 7519 JSON Web Tokens (JWT) passed via `Authorization: Bearer <token>`.
- **Validation Rules**:
  - Valid cryptographic signature.
  - Expiration time (`exp`) strictly enforced.
  - Required claims: subject (`sub`) and assigned role (`role`).
  - Optional privilege claims: `production_write` (boolean) and `attachment_access` (boolean).
- **Cryptographic Algorithms (Production vs. Local)**:
  - **Local Development Exception**: Symmetric HMAC-SHA256 (`HS256`) with a shared secret is permitted for local offline test execution.
  - **Production Architecture**: Asymmetric signature validation using enterprise Identity Provider JSON Web Key Sets (JWKS). (Specific algorithms such as RS256 or ES256 remain open and will be evaluated during the Production Readiness Program).

---

## 4. Role-Based Access Control (RBAC) Specification

Access control is enforced via `platform_security.rbac.YamlPolicyEngine` using declarative rules from `tool_permissions.yaml` (ADR 010).

### Policy Rules:
- **Deny-by-Default**: Every tool request is denied unless an explicit rule in `tool_permissions.yaml` permits it.
- **Fail Closed**: Unknown roles, unmapped tools, or invalid tokens are unconditionally rejected (`DENY`).

### Canonical Roles:
1. **`L1` (Support Agent Tier 1)**: Basic ticket triage and technical knowledge retrieval.
2. **`L2` (Support Engineer Tier 2)**: All L1 capabilities plus read-only database health and log diagnostics.
3. **`L3` (Senior Engineer / Escalation Tier 3)**: All L2 capabilities plus composite cross-system incident investigation (`investigate_incident`).

### Side-Effect Classifications:
- `READ_ONLY`: Queries with zero system side-effects (all 18 registered public tools are classified as `READ_ONLY`).
- `SAFE_WRITE`: Reversible, low-risk state mutations (none registered in Local Development Release 1.0).
- `SENSITIVE_WRITE`: State mutations requiring explicit authorization (none registered).
- `DESTRUCTIVE`: Permanent deletions or schema alterations (strictly prohibited).

### Data Classification Levels:
- `PUBLIC`: Public documentation.
- `INTERNAL`: Internal troubleshooting runbooks and organizational guides.
- `CONFIDENTIAL`: Customer CRM data, ticket messages, diagnostic logs, and database records.
- `RESTRICTED`: Compliance-restricted records and sensitive operational data.
- `SECRET`: Cryptographic keys, passwords, connection strings (never exposed).

### Knowledge Tool RBAC Mapping:
All three public Knowledge tools are explicitly authorized at the `L1` baseline:
- `search_knowledge`: Minimum Role: `L1` | Classification: `READ_ONLY` | Data Level: `INTERNAL`
- `get_runbook`: Minimum Role: `L1` | Classification: `READ_ONLY` | Data Level: `INTERNAL`
- `find_known_issues`: Minimum Role: `L1` | Classification: `READ_ONLY` | Data Level: `INTERNAL`

---

## 5. Attachment Security Policy (Decision D05)

- **Status**: `RESOLVED / ENFORCED`.
- **Policy**: `DENY BY DEFAULT`.
- **Public Tool Exposure**: The public inventory includes only `list_attachments` on SuperOffice MCP, which returns strictly **metadata**:
  - Attachment ID (`attachment_id`)
  - Filename (`filename`)
  - Content type (`content_type`)
  - Size in bytes (`size_bytes`)
- **Prohibition of Raw Content**: The platform does not automatically download, parse, or transmit raw attachment contents (PDF, DOCX, PNG, JPG) to the AI model.
- **Future Pipeline (Deferred)**: Access to raw attachment content requires the explicit `attachment_access` privilege flag, anti-malware scanning, and DLP redaction, and remains deferred to a future phase.

---

## 6. External AI Boundary & Live CRM Privacy (Decision D08)

- **Status**: `OPEN / ENFORCED`.
- **Boundary Policy**:
  - Transmission of confidential, sensitive live SuperOffice CRM customer data to external AI model endpoints is **NOT APPROVED**.
  - Direct ingestion of live customer CRM exports into the Knowledge vector store is **STRICTLY DENIED**.
- **Local Development Conformance**:
  - All local development and test execution uses synthetic sample data and mock fixtures.
  - Decision D08 cannot be marked resolved until an enterprise Data Protection Impact Assessment (DPIA) and organizational data governance sign-off are completed.

---

## 7. Database Diagnostics Security (Decisions D01, D02, D09)

Diagnostics against Microsoft SQL Server are strictly constrained to prevent operational impact or unauthorized data exposure:

1. **D01 — Statement Query Timeout**: Mandatory **5.0-second** timeout (`DIAGNOSTICS_MSSQL_QUERY_TIMEOUT_SECONDS=5`). Any query exceeding 5.0 seconds is immediately cancelled by the database engine.
2. **D02 — Maximum Result Rows**: Hard safety ceiling of **50 rows** (`DIAGNOSTICS_MSSQL_MAX_ROWS=50`). Queries enforce `SELECT TOP (50)` or parameterized limit logic.
3. **D09 — Transaction Isolation**: Mandatory **`SNAPSHOT`** isolation. Operational prerequisite: DBA must confirm `ALLOW_SNAPSHOT_ISOLATION=ON` on target database. The application does not execute DDL (`ALTER DATABASE`). No automatic `READ UNCOMMITTED` fallback.
4. **Strict Prohibitions**:
   - Zero `WITH (NOLOCK)` table hints.
   - Zero `READ UNCOMMITTED` isolation levels.
   - Zero arbitrary SQL execution tools.
   - Zero `SELECT *` wildcard queries; column lists are explicitly enumerated.
   - Fixed, static parameterized queries only.

---

## 8. Application & System Log Security

- **Tool**: `search_logs` on Diagnostics MCP.
- **Status**: `IMPLEMENTED / CONFIGURATION-CONDITIONAL`.
- **Sources**: Local IIS W3C access logs and SuperOffice warning logs.
- **Fail-Closed Semantics**: If any enabled log source fails (e.g. missing directory, permission denied, corrupt file), the tool **fails closed** and reports an error. There is no partial success reporting.
- **Filesystem Boundary**: Strict path isolation; directory traversal (`..`) is blocked, and search is restricted to configured log roots.
- **Investigation Integration**: Direct invocation from `investigate_incident` is **DEFERRED**; investigation application log collector returns `BLOCKED`.

---

## 9. Data Minimization, PII Redaction & Secret Scrubbing

- **Data Minimization Hierarchy**:
  ```text
  Identifier > Metadata > Summary > Redacted Content > Raw Content
  ```
- **Secret Redaction**: Recursively identifies and redacts API keys, bearer tokens, passwords, database connection strings, and private keys from all tool responses before returning them to callers.
- **PII Masking**: Masking of email addresses, phone numbers, personal names, and physical addresses is enforced on all customer-facing entities.

---

## 10. Audit Logging & Traceability

- **Sink**: `JsonStreamAuditSink` emitting structured JSON records to stderr/audit streams.
- **Correlation**: Inbound `X-Correlation-ID` is extracted or generated at the Gateway and attached to all log and audit events.
- **Audit Fields**:
  - `correlation_id`: Unique request tracking identifier.
  - `identity`: Authenticated subject (`sub`).
  - `role`: Caller role (`role`).
  - `server`: Target backend MCP server.
  - `tool`: Requested tool name.
  - `authorized`: Boolean outcome.
  - `decision_reason`: Policy evaluation explanation.
  - `timestamp`: UTC ISO-8601 timestamp.
- **Zero Secret Logging**: Passwords, tokens, API keys, and connection strings are strictly stripped before writing audit logs.

---

## 11. Backend Network & Downstream Trust Model

1. **Mandatory Backend Reachability Invariant**:
   - Backend MCP Streamable HTTP endpoints (`so-mcp`, `diag-mcp`, `kb-mcp`, `investigation-mcp`) must **NOT** be directly reachable from external AI clients or untrusted networks.
   - External MCP clients communicate exclusively with the Gateway (port 8000).
   - Gateway $\rightarrow$ backend MCP communication occurs through the internal network.
   - **Production Enablement Prerequisite**: Production second-hop traffic is **BLOCKED** until production topology, network policy, and service isolation controls are selected, provisioned, and validated.
2. **Downstream Trust Model**:
   - Current local second-hop trust is enforced via **Network-Bound Caller Authorization** and trusted internal transport context (`X-User-ID`, `X-User-Role`, `X-Production-Write`, `X-Attachment-Access`, `X-Correlation-ID`) derived exclusively from validated Gateway `SecurityContext`.
   - Production service-to-service cryptographic trust mechanisms are **not yet selected** and will be determined during the Production Readiness Program.
   - Raw external Bearer JWTs terminate strictly at the Gateway and are never passed on internal second-hop calls.
   - In Phase 4.1 composition, `investigation-mcp` sends an **EMPTY** custom header set on downstream calls to `so-mcp` and `diag-mcp`.
3. **DNS Rebinding & Host-Header Protection**:
   - `TransportSecuritySettings` and `allowed_hosts` provide DNS rebinding and Host-Origin header protection at the FastMCP edge.
   - They do not replace authentication or authorization; centralized JWT validation and RBAC remain enforced at the Gateway.

---

## 12. Local-Development-Only Exceptions

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
