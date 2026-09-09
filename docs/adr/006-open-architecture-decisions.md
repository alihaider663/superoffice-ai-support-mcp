# ADR 006 — Open Architecture Decisions

## Status

Open

## Context

The project documentation establishes clear architectural principles, security policies, and domain boundaries. However, several implementation-level decisions remain unmade. These decisions must be resolved before Phase 1 implementation begins.

This ADR catalogs decisions that are **not yet established** in the existing project documentation.

---

## Decision 1 — MCP Transport Protocol (RESOLVED)

**Status**: Resolved in [ADR 007 — Streamable HTTP Transport](007-streamable-http-transport.md).

### Resolution Summary
Streamable HTTP selected for all runtime communication (development and production), with stdio permitted only for isolated unit testing of individual MCP servers.

---

## Decision 2 — MCP Gateway Implementation (RESOLVED)

**Status**: Resolved in [ADR 008 — Custom Python MCP Gateway](008-custom-python-gateway.md).

### Resolution Summary
Custom Python service using Python 3.12+, MCP Python SDK v2, Pydantic, and httpx to enable MCP protocol-aware tool-level authorization, request proxying, output filtering, and centralized security enforcement.

---

## Decision 3 — Authentication Mechanism (RESOLVED)

**Status**: Resolved in [ADR 009 — JWT Bearer Token Authentication](009-jwt-authentication.md).

### Resolution Summary
JWT Bearer tokens validated at the MCP Gateway, supporting HMAC in development and asymmetric keys/JWKS in production with claims-based identity and role propagation.

---

## Decision 4 — RBAC Implementation (RESOLVED)

**Status**: Resolved in [ADR 010 — Declarative YAML RBAC Configuration](010-yaml-rbac-configuration.md).

### Resolution Summary
Declarative YAML-based tool permission configuration (`tool_permissions.yaml`) loaded at startup by the Gateway, evaluating L1/L2/L3 role hierarchy, tool side-effect classifications, and specific required privileges (`production_write`, `attachment_access`) under a deny-by-default rule.

---

## Open Decision 5 — Deployment Topology

### Question

What is the target deployment topology?

### Options

- **Single-host Docker Compose** — All servers on one host. Suitable for development/staging.
- **Container orchestration (Kubernetes, Docker Swarm)** — Full production scaling.
- **Serverless containers** — Per-request scaling, no idle costs.
- **Hybrid** — Docker Compose for development, orchestration for production.

### Considerations

- MCP servers must be independently deployable (project requirements).
- Horizontal scaling is required (architecture documentation).
- The existing SuperOffice environment is load-balanced.
- Container-friendly deployment is explicitly required.
- Docker is listed in the technology stack.

### Impact

MEDIUM — Affects operational procedures but not application architecture.

---

## Open Decision 6 — Secret Management

### Question

How will production secrets be managed?

### Options

- **Environment variables** — Current approach (`.env`). Simple but limited rotation and auditability.
- **Secret manager** (e.g., HashiCorp Vault, Azure Key Vault, AWS Secrets Manager) — Dynamic secrets, rotation, audit trail.
- **Kubernetes Secrets** — If deploying on Kubernetes. Encrypted at rest with proper configuration.

### Considerations

- The `.env.example` contains placeholders for database credentials, API keys, and OAuth secrets.
- The security model prohibits hardcoded credentials.
- Production environments require secret rotation capability.
- Audit logging of secret access may be required.

### Impact

MEDIUM — Affects deployment security but not application architecture.

---

## Open Decision 7 — Attachment Scanning Mechanism

### Question

What technology will be used for attachment security scanning?

### Options

- **ClamAV** — Open-source antivirus scanning. Widely used for file scanning.
- **Cloud-based scanning service** — Provider-managed, regularly updated signatures.
- **Custom content inspection** — Application-level DLP rules for PII and credential detection.
- **Combination** — Malware scanning + DLP content inspection.

### Considerations

- The security model requires "security inspection" and "DLP / redaction" for attachments.
- Binary formats (PDF, images) require specialized parsing for embedded content.
- OCR may be needed for image-based attachments containing text.
- Scanning adds latency to attachment access.

### Impact

MEDIUM — Affects the attachment access pipeline implementation.

---

## Open Decision 8 — Audit Log Storage

### Question

Where will audit logs be stored?

### Options

- **Application database** — Alongside other data. Simple but mixes concerns.
- **Dedicated audit database** — Separate, append-only store. Tamper-resistant.
- **Structured logging to external system** (e.g., ELK, Splunk, Azure Monitor) — Centralized, searchable, existing infrastructure.
- **Supabase** — Already in the architecture as the knowledge store.

### Considerations

- Audit logs must capture: correlation ID, identity, server, tool, authorization result, timestamp, dependency, result status.
- Audit logs must never contain secrets, tokens, or sensitive attachment content.
- Audit log integrity is important — append-only or tamper-evident storage is preferred.
- The volume of audit logs could be significant under load.

### Impact

MEDIUM — Affects observability and compliance capability.

---

## Open Decision 9 — Observability Stack

### Question

What observability tooling will be used?

### Options

- **Structured logging only** — JSON logs to stdout. Minimal infrastructure.
- **OpenTelemetry** — Standardized traces, metrics, and logs. Vendor-neutral.
- **Application-specific metrics** — Custom Prometheus/StatsD metrics.
- **Existing organizational tools** — Integrate with whatever monitoring the SuperOffice environment already uses.

### Considerations

- The project requires "observable" as a non-functional requirement.
- Structured logging is already specified in the Python standards.
- Cross-server correlation requires distributed tracing or correlation IDs.
- The investigate-bug workflow relies heavily on correlation IDs and timestamps.

### Impact

MEDIUM — Affects debugging and operational visibility.

---

## Open Decision 10 — Development vs. Production Isolation

### Question

How will development and production environments be isolated?

### Options

- **Environment variables only** — `APP_ENV=development` vs. `APP_ENV=production`.
- **Separate infrastructure** — Distinct databases, networks, and credentials.
- **Feature flags** — Runtime switches for production-only capabilities.
- **Combination** — Environment variables + separate infrastructure + configuration profiles.

### Considerations

- The `.env.example` uses `APP_ENV=development` and `PRODUCTION_ACCESS_ENABLED=false`.
- Development must use mocked systems and test data (project requirements).
- Real production credentials must never appear in development environments.
- The investigation workflow must support both environments.

### Impact

MEDIUM — Affects development safety and deployment procedures.

---

## Open Decision 11 — AI Provider Boundary

### Question

What specific controls govern data crossing the AI provider boundary?

### Considerations

- The security model states data sent to an external AI provider must be treated as leaving the protected boundary.
- If organizational policy requires that customer data never leaves the environment, a self-hosted model is needed.
- The platform itself is model-independent (ADR 005), but the deployment must address this policy question.
- This is an organizational/compliance decision, not a technical architecture decision, but it has direct technical implications (e.g., whether to deploy a private model endpoint).

### Impact

HIGH — Affects whether an external AI provider can be used at all for investigations involving customer data.

---

## Decision 12 — Knowledge Store Technology (RESOLVED)

**Status**: Resolved in Phase 7.

### Resolution Summary
Direct PostgreSQL with the `pgvector` extension (version 0.8.6) in database `superoffice_ai_knowledge` and schema `knowledge` was selected, implemented, and verified for Knowledge storage and semantic retrieval, using `FastEmbedEmbeddingProvider` (`BAAI/bge-small-en-v1.5`, 384 dimensions). The early Supabase candidate was superseded by direct PostgreSQL + pgvector.

---

## Decision 13 — Error Handling and Resilience Strategy (RESOLVED)

**Status**: Resolved in Phase 1B / Phase 2B.

### Resolution Summary
Unified error taxonomy implemented in `platform_core.errors` (`PlatformBaseError`, `AuthenticationError`, `AuthorizationError`, `RateLimitError`, `UpstreamServiceError`, `NotFoundError`, etc.) with fail-fast validation, typed error codes, and safe client sanitization.

---

## Authoritative Architecture Decision Ledger (D01–D09)

Note: For the authoritative, current decision ledger governing the platform's runtime constraints, see **`docs/project-status.md`** (Decisions D01 through D09):
- **D01**: Diagnostics MSSQL statement query timeout = 5.0 seconds (RESOLVED)
- **D02**: Diagnostics MSSQL maximum result rows = 50 rows (RESOLVED)
- **D03**: Declarative YAML tool-level RBAC (RESOLVED)
- **D04**: Attachment MD5 metadata discrepancy (OPEN / NON-BLOCKING)
- **D05**: Attachment authorization & deny-by-default (RESOLVED / ENFORCED)
- **D06**: stdout/stderr documentation normalization (NON-BLOCKING)
- **D07**: Infrastructure detailed adapter contracts (DEFERRED)
- **D08**: External AI / sensitive production CRM boundary (OPEN / ENFORCED)
- **D09**: Diagnostics MSSQL transaction isolation = SNAPSHOT (RESOLVED / APPROVED)

