# SuperOffice AI Support MCP Platform — Architecture

## 1. Purpose

The SuperOffice AI Support MCP Platform provides a secure, modular interface between an AI support agent and enterprise systems used for SuperOffice L1/L2/L3 troubleshooting.

The platform is designed to investigate incidents across:

* SuperOffice CRM entities and tickets
* Application and API diagnostics
* Database diagnostic views (DMVs)
* Infrastructure health boundaries
* Internal technical knowledge, runbooks, and known issues

The architecture must remain independent of any particular AI model provider (ADR 005).

---

## 2. High-Level Architecture

```text
                               AI Support Agent
                                      │
                                      ▼
                           [ 1. MCP Gateway (8000) ]
                             (Perimeter Security)
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            │                         │                         │
            ▼                         ▼                         ▼
   SuperOffice MCP (8001)    Diagnostics MCP (8002)    Knowledge MCP (8003)
            ▲                         ▲                         │
            │                         │                         │
            └────────────┬────────────┘                         │
                         │ (Internal Streamable HTTP)           │
                         │                                      │
               Investigation MCP (8005)                         │
                         │                                      │
            ┌────────────┴────────────┬─────────────────────────┘
            │                         │
            ▼                         ▼
   Application Services      Application Services
   (Ticket, Incident, etc.)   (Knowledge Retrieval)
            │                         │
            ▼                         ▼
   Integration Clients       Integration Clients
            │                         │
   ┌────────┴────────┬────────────────┴────────┬────────────────────────┐
   │                 │                         │                        │
   ▼                 ▼                         ▼                        ▼
SuperOffice REST    MSSQL (Async)          PostgreSQL              Infrastructure
     WebAPI          SQL Server             + pgvector                Boundary
                                      (superoffice_ai_knowledge)    (0 public tools)
```

---

## 3. The Six-Layer Architecture

The platform strictly enforces a **Six-Layer Architecture**. Observability is a **cross-cutting concern** spanning all operational layers; it is never designated as a separate sequential layer (there is no "Layer 7 Observability").

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

#### 1. MCP Layer
Exposes controlled capabilities to AI clients via the official Model Context Protocol (MCP) Python SDK over Streamable HTTP (ADR 007). MCP runtimes are stateless. They contain no AI reasoning, no direct database drivers, and no heavy business logic.

#### 2. Security Layer
The Gateway is the hardened perimeter security boundary. It enforces JWT Bearer authentication, extracts caller identity and privilege context, applies declarative YAML RBAC (`tool_permissions.yaml`), enforces rate limits, logs structured audit records, and performs recursive output sanitization.

#### 3. Investigation Layer
Encapsulates domain diagnostic logic, state machine lifecycles (`IncidentInvestigationStateMachine`), multi-source evidence collection, hypothesis generation, and incident timeline correlation (`platform_investigation`).

#### 4. Application Service Layer
Coordinates domain operations and business workflows across integration clients:
* Ticket investigation and summary synthesis
* Knowledge vector search and runbook retrieval
* Database diagnostic health checks and slow-query inspection
* Log parsing and correlation

#### 5. Integration Layer
Contains strongly typed, resilient client adapters communicating with external systems:
* `SuperOfficeRestClient`: Communicates with SuperOffice REST WebAPI
* `MssqlRepository`: Communicates with Microsoft SQL Server using SQLAlchemy 2.0 Async + `aioodbc`
* `KnowledgePostgresRepository`: Communicates with PostgreSQL + `pgvector` (`asyncpg`)
* External integrations must never be embedded directly inside MCP tool handlers.

#### 6. Infrastructure Layer
Defines the host environment, container process model, system resources, and OS security boundaries. Direct host access from upper layers is strictly guarded.

#### Cross-Cutting: Observability
Observability spans every layer through contextual JSON structured logging (`structlog`), correlation tracking (`X-Correlation-ID`), audit sinks (`JsonStreamAuditSink`), and execution timing. It is **not** a sequential architectural layer.

---

## 4. Backend Ownership & Isolation Boundaries

To guarantee security, isolation, and data minimization:

| Backend Resource | Sole Owner Service | Integration Protocol | Direct AI Access | Direct Gateway Access |
| :--- | :--- | :--- | :--- | :--- |
| **SuperOffice Business Data** | SuperOffice MCP (`so-mcp`) | SuperOffice REST API | **PROHIBITED** | **NO** |
| **MSSQL Database Diagnostics** | Diagnostics MCP (`diag-mcp`)| Async SQLAlchemy / `aioodbc` | **PROHIBITED** | **NO** |
| **Application & API Logs** | Diagnostics MCP (`diag-mcp`)| Local Filesystem / W3C Parser| **PROHIBITED** | **NO** |
| **Technical Knowledge & Runbooks** | Knowledge MCP (`kb-mcp`) | PostgreSQL + `pgvector` | **PROHIBITED** | **NO** |
| **Host & System Diagnostics** | Infrastructure MCP (Boundary)| Host / OS Primitives | **PROHIBITED** | **NO** |

### Strict Isolation Invariants
- **AI Direct Access Prohibited**: The AI has no direct access to MSSQL, PostgreSQL, attachments, infrastructure, shells/filesystems, or enterprise credentials/secrets.
- **Gateway Direct Database Access Prohibited**: The Gateway has no direct database access, imports zero database drivers, and routes exclusively over Streamable HTTP.
- **Microservice Composition**: `investigation-mcp` calls downstream MCP servers (`so-mcp`, `diag-mcp`) via internal Streamable HTTP with an empty custom header set; Bearer JWTs terminate at the Gateway.

---

## 5. Statelessness

MCP servers must be stateless (ADR 004):
- Do not store durable investigation state or user sessions in process memory.
- Request-scoped ephemeral state (`InMemoryInvestigationStore`) is used during single tool invocations.
- Durable state belongs in the application and database layer.
- This design enables horizontal scaling, load balancing, and independent restarts.

---

## 6. Security Principles & Data Flow

The existence of data does not imply permission to expose that data to the AI:

```text
External System
      │
      ▼
Integration Client
      │
      ▼
Application Service
      │
      ▼
Security / Policy Layer (Sanitization & PII Redaction)
      │
      ▼
MCP Tool (Data Minimization)
      │
      ▼
AI Agent
```

### Core Security Rules:
- **Least Privilege**: Return the minimum information necessary (identifier > metadata > summary > redacted content).
- **Attachments (Decision D05)**: Deny-by-default. `list_attachments` returns metadata only. No raw attachment files are automatically sent to the AI.
- **External AI Boundary (Decision D08)**: Transmission of confidential live CRM data to external AI is not approved; knowledge ingestion of customer CRM data is denied.
- **Database Safety (Decisions D01, D02, D09)**: Hard 5s statement timeout, 50-row limit, mandatory SNAPSHOT isolation, zero `WITH (NOLOCK)` hints, zero arbitrary SQL.
