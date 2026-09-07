# SuperOffice AI Support MCP Platform — Architecture

## 1. Purpose

The SuperOffice AI Support MCP Platform provides a secure, modular interface between an AI support agent and enterprise systems used for SuperOffice L1/L2/L3 troubleshooting.

The platform is designed to investigate incidents across:

* SuperOffice
* Application services
* APIs
* Database
* Infrastructure
* Internal knowledge

The architecture must remain independent of any particular AI model provider.

---

## 2. High-Level Architecture

```text
                    AI Support Agent
                           |
                           v
                    MCP Gateway
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
   SuperOffice MCP   Diagnostics MCP   Knowledge MCP
          |                |                |
          |                v                |
          |          Infrastructure MCP    |
          |                                 |
          +----------------+----------------+
                           |
                           v
                  Application Services
                           |
                           v
                  Integration Clients
                           |
        +------------------+------------------+
        |         |          |                |
        v         v          v                v
   SuperOffice  MSSQL    App/API Logs     Supabase
```

---

## 3. Architectural Layers

### AI Agent

Responsible for:

* reasoning
* planning
* hypothesis generation
* evidence correlation
* investigation orchestration

The AI must not directly access databases, infrastructure or SuperOffice.

---

### MCP Gateway

Responsible for:

* authentication
* authorization
* RBAC
* tool permissions
* policy enforcement
* request validation
* rate limiting
* audit correlation
* data filtering

The Gateway is a security boundary.

---

### MCP Servers

MCP servers expose controlled capabilities.

They must not contain large amounts of business logic.

They must not perform AI reasoning.

---

### Application Services

Application services implement business workflows.

Examples:

* ticket investigation
* incident correlation
* attachment processing
* knowledge retrieval
* diagnostic correlation

---

### Integration Clients

Integration clients communicate with external systems.

Examples:

* SuperOffice API client
* MSSQL client
* logging client
* infrastructure client
* Supabase client

External integrations must not be embedded directly inside MCP tool functions.

---

## 4. MCP Server Boundaries

### SuperOffice MCP

Responsible for SuperOffice entities and ticket operations.

### Diagnostics MCP

Responsible for technical diagnostics and evidence collection.

### Knowledge MCP

Responsible for internal technical knowledge and historical incidents.

### Infrastructure MCP

Responsible for infrastructure health and diagnostics.

Each server must have a clear ownership boundary.

---

## 5. Statelessness

MCP servers must be stateless.

Do not store durable investigation state in process memory.

Durable state belongs in the application/data layer.

This allows horizontal scaling and load balancing.

---

## 6. Security Principle

The existence of data does not imply permission to expose that data to the AI.

Use:

```text
Need
  ->
Authorization
  ->
Policy
  ->
Minimum Data
  ->
AI
```

not:

```text
MCP has access
  ->
AI receives everything
```

---

## 7. Data Flow

Sensitive data should follow:

```text
External System
      |
      v
Integration Client
      |
      v
Application Service
      |
      v
Security / Policy Layer
      |
      v
MCP Tool
      |
      v
AI Agent
```

Filtering must occur before sensitive data reaches the model.

---

## 8. Scalability

The platform must support:

* horizontal scaling
* stateless MCP servers
* load balancing
* connection pooling
* timeouts
* retries where safe
* circuit breakers where appropriate

---

## 9. Architectural Rules

* Do not create giant MCP tools.
* Do not expose unrestricted database access.
* Do not expose unrestricted shell access.
* Do not put secrets in source code.
* Do not return attachments automatically.
* Do not return unnecessary PII.
* Do not couple MCP tools directly to an AI provider.
* Do not bypass authorization for convenience.
* Prefer read-only operations.
* Document significant architectural decisions.
