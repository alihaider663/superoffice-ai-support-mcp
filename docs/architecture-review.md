# Architecture Review Report

## SuperOffice AI Support MCP Platform — Phase 0

**Date**: 2026-08-28
**Status**: Architecture and governance review complete. Implementation has not started.

---

## 1. Executive Summary

The SuperOffice AI Support MCP Platform's documentation establishes a well-considered, security-first architecture for AI-assisted L1/L2/L3 support. The documentation suite is internally consistent, with no critical contradictions identified between documents. The architecture correctly identifies the AI model as an untrusted boundary and enforces deny-by-default data access.

**Key strengths**: Strong security posture, clear domain separation, explicit data classification, and model-provider independence.

**Key gaps**: Several implementation-level decisions remain open — notably the MCP Gateway implementation, authentication mechanism, RBAC implementation, and MCP transport selection. These must be resolved before Phase 1.

**Overall assessment**: The architecture is sound and ready for implementation planning, contingent on resolving the open decisions cataloged in ADR 006.

---

## 2. Current Architecture

### Layers

```text
AI Support Agent
       ↓
MCP Gateway (security boundary)
       ↓
┌──────────────┬──────────────┬──────────────┬──────────────┐
│ SuperOffice  │ Diagnostics  │  Knowledge   │Infrastructure│
│     MCP      │     MCP      │     MCP      │     MCP      │
└──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┘
       └──────────────┴──────────────┴──────────────┘
                             ↓
                    Application Services
                             ↓
                    Integration Clients
                             ↓
       ┌─────────┬──────────────┬──────────┐
       │SuperOff.│ MSSQL        │ Supabase │
       └─────────┴──────────────┴──────────┘
```

### Documents Reviewed

| Document | Location |
|----------|----------|
| Project architecture rules | `.agents/rules/project-architecture.md` |
| Security rules | `.agents/rules/security.md` |
| Python standards | `.agents/rules/python-standards.md` |
| Feature implementation workflow | `.agents/workflows/implement-feature.md` |
| Bug investigation workflow | `.agents/workflows/investigate-bug.md` |
| Add MCP tool workflow | `.agents/workflows/add-mcp-tool.md` |
| Security review workflow | `.agents/workflows/security-review.md` |
| Architecture documentation | `docs/architecture.md` |
| Security model | `docs/security-model.md` |
| Project requirements | `docs/project-requirements.md` |
| Server responsibilities | `docs/server-responsibilities.md` |
| Data classification | `docs/data-classification.md` |
| Investigation flow | `docs/investigation-flow.md` |
| Environment configuration | `.env.example` |
| Repository ignore rules | `.gitignore` |
| Project README | `README.md` |

---

## 3. Architecture Strengths

### S1 — Security-First Design
**Level**: INFORMATIONAL

The entire documentation suite is built around deny-by-default security. The security model is not an afterthought — it is the foundational constraint. The explicit statement that "the AI model must never be considered a security boundary" is critical and correctly applied throughout.

### S2 — Clear Separation of Concerns
**Level**: INFORMATIONAL

The five-layer architecture (AI Agent → Gateway → MCP Servers → Application Services → Integration Clients → External Systems) establishes clean boundaries. Each layer has documented responsibilities and explicit "does not own" constraints.

### S3 — Data Classification System
**Level**: INFORMATIONAL

The four-level data classification (Public → Internal → Confidential → Restricted → Secret) with explicit AI access rules for each level provides a clear framework for implementation decisions.

### S4 — Comprehensive Workflow Documentation
**Level**: INFORMATIONAL

The four workflows (implement-feature, investigate-bug, add-mcp-tool, security-review) provide guardrails that will help maintain architectural integrity during implementation.

### S5 — Model Provider Independence
**Level**: INFORMATIONAL

The explicit requirement for AI provider independence ensures the platform remains adaptable as the model landscape evolves.

### S6 — Attachment Deny-by-Default
**Level**: INFORMATIONAL

The multi-stage attachment access pipeline (authorization → purpose → policy → scanning → DLP → minimization → AI) is thorough and correctly classifies all attachments as Level 3 Restricted.

### S7 — Evidence-Driven Investigation Methodology
**Level**: INFORMATIONAL

The investigation flow and bug investigation workflow enforce systematic, evidence-driven investigation rather than blind tool invocation. The confidence classification (CONFIRMED/PROBABLE/POSSIBLE/UNKNOWN) prevents premature conclusions.

---

## 4. Identified Risks

### R1 — Gateway Is a Single Point of Failure
**Severity**: HIGH

The MCP Gateway is the sole security enforcement point. If the Gateway is unavailable, all MCP access is blocked. If the Gateway is misconfigured, security may be bypassed.

**Mitigation**: The Gateway must be designed for high availability. Consider redundant Gateway instances. Gateway configuration should be tested as part of the security test suite.

---

### R2 — Connection Pool Exhaustion Under Horizontal Scaling
**Severity**: HIGH

Stateless MCP servers (ADR 004) with independent connection pools could collectively exhaust database connection limits. If 10 Diagnostics MCP instances each maintain a pool of 10 connections, the database receives 100 concurrent connections.

**Mitigation**: Establish connection pool limits per instance. Consider a connection pooling proxy (e.g., PgBouncer for Supabase, or equivalent for MSSQL). Document maximum instance counts per database.

---

### R3 — Incomplete PII Redaction in Unstructured Data
**Severity**: HIGH

Logs, error messages, and attachment content may contain PII in unpredictable locations. Regex-based redaction may miss edge cases. Binary formats require specialized parsing.

**Mitigation**: Implement layered redaction (structured field removal + pattern-based scanning). Accept that perfect redaction of unstructured content is difficult and document the residual risk. Test redaction against representative data patterns.

---

### R4 — No Defined Rate Limiting Strategy
**Severity**: MEDIUM

The Gateway lists "rate limiting" as a responsibility, but no document specifies rate limiting policies, per-user limits, per-tool limits, or backpressure behavior.

**Mitigation**: Define rate limiting policies before production deployment. Consider per-role limits (L1 may have lower limits than L3).

---

### R5 — DLP for Binary Attachments Requires Specialized Tooling
**Severity**: MEDIUM

The attachment security pipeline includes DLP/redaction, but PDF parsing, image OCR, and DOCX inspection require specialized libraries that are not yet selected.

**Mitigation**: Resolve Open Decision 7 (Attachment Scanning Mechanism) in ADR 006. Evaluate libraries during Phase 1 planning.

---

### R6 — Audit Log Volume Under Load
**Severity**: LOW

The audit logging specification captures detailed per-request information (correlation ID, identity, server, tool, authorization result, timestamp, dependency, result status). Under high load with multiple concurrent investigations, audit log volume could be significant.

**Mitigation**: Resolve Open Decision 8 (Audit Log Storage). Design for append-only, high-throughput storage. Consider log rotation and retention policies.

---

## 5. Contradictions

### C1 — No Direct Contradictions Found
**Level**: INFORMATIONAL

After thorough cross-referencing of all 16 documents, no contradictory requirements were identified. The documents are internally consistent across:

- Security model ↔ data classification ↔ security rules
- Architecture ↔ server responsibilities ↔ project architecture rules
- Investigation flow ↔ bug investigation workflow
- Feature workflow ↔ add-mcp-tool workflow ↔ security review workflow

### C2 — Minor Phrasing Ambiguity: Supabase Status
**Level**: LOW

`project-requirements.md` says "Supabase/pgvector **may** be used for knowledge retrieval" (conditional). `architecture.md` includes Supabase in the architecture diagram as an external system. `server-responsibilities.md` lists "Supabase Client" as an integration client.

This is not a contradiction but an ambiguity: is Supabase a confirmed technology choice or a candidate? The architecture diagram and integration client listing suggest it is confirmed, while the requirements phrasing suggests it is still under evaluation.

**Resolution**: Documented as Open Decision 12 in ADR 006.

---

## 6. Security Findings

### SF1 — AI Model Correctly Excluded as Security Boundary
**Level**: INFORMATIONAL

All documents consistently enforce that security must be implemented in deterministic code, never delegated to the LLM. This is correctly applied at every layer.

### SF2 — Deny-by-Default Correctly Applied Across All Data Levels
**Level**: INFORMATIONAL

The data classification system (Levels 0–4) with deny-by-default for Levels 3–4 and controlled access for Level 2 is consistently documented across `data-classification.md`, `security-model.md`, and `.agents/rules/security.md`.

### SF3 — Production Write Controls Are Documented but Not Specified
**Level**: MEDIUM

Multiple documents require "explicit authorization" and "deterministic policy enforcement" for production writes. The `.env.example` includes `PRODUCTION_ACCESS_ENABLED=false`. However, no document specifies the exact authorization mechanism for production writes (e.g., approval workflow, dual authorization, time-limited tokens).

**Recommendation**: Define the production write authorization mechanism before implementing any write tools.

### SF4 — Secret Redaction in Error Responses
**Level**: MEDIUM

The `add-mcp-tool.md` workflow correctly states "Do not expose: stack traces, credentials, connection strings, internal secrets." However, no document specifies how unhandled exceptions are caught and sanitized at the MCP server boundary. An unhandled exception could leak internal information.

**Recommendation**: Implement a global exception handler at the MCP server boundary that sanitizes all error responses before they reach the AI.

### SF5 — No Input Validation Framework Specified
**Level**: MEDIUM

The `add-mcp-tool.md` workflow requires input validation (identifiers, dates, time ranges, limits). Pydantic models provide structural validation, but no document specifies business-rule validation (e.g., maximum time window for log searches, maximum result count, allowed ticket ID formats).

**Recommendation**: Define input validation constraints as part of each tool's specification during implementation.

### SF6 — `.env.example` Format Is Non-Standard
**Level**: LOW

The `.env.example` file uses section headers without comment markers (e.g., `Security` instead of `# Security`). While this doesn't affect security directly, it could cause parsing errors with standard `.env` file parsers that do not expect non-key-value lines without comment prefixes.

**Recommendation**: Prefix section headers with `#` for compatibility with standard dotenv parsers.

---

## 7. MCP Boundary Findings

### BF1 — Server Boundaries Are Clear
**Level**: INFORMATIONAL

Each MCP server has a documented "Owns" and "Does Not Own" list in `server-responsibilities.md`. This provides clear guidance for tool placement.

| Server | Domain |
|--------|--------|
| SuperOffice MCP | Tickets, customers, persons, companies, attachments, notes, replies |
| Diagnostics MCP | App logs, API logs, HTTP errors, timeouts, DB diagnostics |
| Knowledge MCP | Documentation, runbooks, known issues, historical incidents |
| Infrastructure MCP | Server health, CPU, memory, disk, services, endpoints, load balancer |
| Gateway | Auth, RBAC, tool permissions, rate limiting, audit, policy, filtering |

### BF2 — Diagnostics MCP Scope
**Level**: INFORMATIONAL

With the removal of WSO2 and Automic/UC4 from the project scope, Diagnostics MCP now covers application logs, API logs, and database diagnostics. This is a well-focused domain that does not require sub-domain partitioning.

**Recommendation**: If additional diagnostic domains are added in the future, reassess whether sub-domain boundaries within Diagnostics MCP are warranted.

### BF3 — Cross-Domain Investigation Correctly Delegated
**Level**: INFORMATIONAL

The ownership rule correctly states: "If a capability crosses multiple domains, place orchestration in the application/service layer rather than creating cross-domain MCP servers." This prevents the common anti-pattern of creating MCP tools that span multiple external systems.

### BF4 — Gateway vs. Application Services Boundary
**Level**: LOW

The Gateway owns "output filtering" and "data filtering." Application Services own data minimization and business logic. The boundary between Gateway-level filtering (e.g., removing fields based on RBAC) and Application Service-level filtering (e.g., summarizing data) should be clarified during implementation.

**Recommendation**: Establish a clear convention: the Gateway handles authorization-based field removal (RBAC), while Application Services handle content transformation (summarization, redaction).

---

## 8. Scalability Findings

### SC1 — Stateless Design Enables Horizontal Scaling
**Level**: INFORMATIONAL

The stateless MCP server requirement (ADR 004) correctly enables horizontal scaling. No durable state is stored in process memory. This is well-aligned with the existing load-balanced SuperOffice environment.

### SC2 — Connection Pool Exhaustion Risk
**Level**: HIGH

See Risk R2. Stateless servers with independent pools can collectively exhaust database connection limits. This must be addressed in the deployment topology and connection pooling strategy.

### SC3 — No Circuit Breaker Specification
**Level**: MEDIUM

The architecture mentions "circuit breakers where appropriate" but no document specifies circuit breaker thresholds, fallback behavior, or which external systems warrant circuit breakers.

**Recommendation**: Define circuit breaker policies for each external system (SuperOffice API, MSSQL, Supabase) during implementation. Prioritize systems with known reliability variability.

### SC4 — Timeout Strategy Not Specified
**Level**: MEDIUM

The architecture requires "timeouts" and the database security model requires "query timeout." No document specifies default timeout values, per-system timeout configuration, or timeout propagation (e.g., should the MCP tool timeout include downstream timeouts?).

**Recommendation**: Define a timeout hierarchy: MCP tool timeout > Application Service timeout > Integration Client timeout. Ensure the outer timeout is always larger than the inner timeout.

### SC5 — Load Balancer Compatibility
**Level**: INFORMATIONAL

The architecture correctly notes that SuperOffice is load-balanced and that MCP servers must support load balancing. The stateless design ensures compatibility. The MCP transport decision (Open Decision 1) will determine specific load balancer configuration requirements.

---

## 9. Open Decisions

Thirteen decisions were originally cataloged in `docs/adr/006-open-architecture-decisions.md`. The four critical pre-implementation decisions were resolved in Phase 0.5:

- **Decision 1 (MCP Transport)**: Resolved in [ADR 007](adr/007-streamable-http-transport.md) — Streamable HTTP
- **Decision 2 (MCP Gateway)**: Resolved in [ADR 008](adr/008-custom-python-gateway.md) — Custom Python MCP-aware Gateway
- **Decision 3 (Authentication)**: Resolved in [ADR 009](adr/009-jwt-authentication.md) — JWT Bearer tokens
- **Decision 4 (RBAC)**: Resolved in [ADR 010](adr/010-yaml-rbac-configuration.md) — Declarative YAML configuration

### Remaining Open Decisions

| Priority | Decisions |
|----------|-----------|
| During Phase 1 | Deployment topology (5), Secret management (6), Error handling strategy (13) |
| Before Production | Attachment scanning (7), Audit log storage (8), Observability (9), Dev/prod isolation (10), AI provider boundary (11), Knowledge store (12) |

---

## 10. Recommended Next Steps

1. **Fix `.env.example` Format** — Add `#` prefixes to section headers for dotenv parser compatibility (Finding SF6).

2. **Define Error Handling Convention** — Establish a typed error taxonomy and global exception handler before implementing any MCP tools (Finding SF4, Open Decision 13).

3. **Define Timeout Hierarchy** — Establish default timeout values and propagation rules before implementing integration clients (Finding SC4).

4. **Begin Phase 1 Planning** — With the Gateway, transport, auth, and RBAC decisions established in ADRs 007–010, proceed with Phase 1 scaffolding and initial MCP server implementation (recommended: Knowledge MCP, as it has the simplest security requirements and can validate the architecture end-to-end without accessing production customer data).

---

## Appendix A — Finding Classification Key

| Level | Meaning |
|-------|---------|
| CRITICAL | Blocks implementation. Must be resolved immediately. |
| HIGH | Significant risk. Must be resolved before production. |
| MEDIUM | Notable concern. Should be addressed during implementation. |
| LOW | Minor issue. Can be resolved during normal development. |
| INFORMATIONAL | Observation or positive finding. No action required. |

---

## Appendix B — ADR Index

| ADR | Title | Status |
|-----|-------|--------|
| 001 | Modular MCP Architecture | Accepted |
| 002 | Deny-by-Default Data Access | Accepted |
| 003 | Attachment Security | Accepted |
| 004 | Stateless MCP Servers | Accepted |
| 005 | Model Provider Independence | Accepted |
| 006 | Open Architecture Decisions | Open (Updated) |
| 007 | Streamable HTTP Transport | Accepted |
| 008 | Custom Python MCP Gateway | Accepted |
| 009 | JWT Bearer Token Authentication | Accepted |
| 010 | Declarative YAML RBAC Configuration | Accepted |
