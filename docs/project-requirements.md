# Project Requirements

## 1. Project Name

SuperOffice AI Support MCP Platform

---

## 2. Objective

Build a professional MCP-based platform that enables AI-assisted L1/L2/L3 SuperOffice support.

The system should help diagnose:

* ticket issues
* API failures
* application errors
* database problems
* infrastructure problems

---

## 3. Functional Requirements

### Ticket Investigation

The platform must be able to:

* retrieve ticket information
* search tickets
* retrieve ticket history
* identify ticket status
* retrieve customer references
* list attachments
* retrieve attachment metadata

---

### Application Diagnostics

The platform must support:

* application log search
* API log search
* HTTP error detection
* timeout detection
* correlation ID analysis

---

### Database Diagnostics

The platform must support controlled:

* slow query analysis
* deadlock detection
* blocking session detection
* query diagnostics

Unrestricted SQL must not be exposed.

---

### Infrastructure

The platform should support:

* server health
* CPU
* memory
* disk
* service status
* endpoint health
* load balancer health

---

### Knowledge

The platform should provide:

* internal documentation search
* runbook retrieval
* known issue detection
* historical incident search
* resolution patterns

Supabase/pgvector may be used for knowledge retrieval.

---

## 4. Non-Functional Requirements

The system must be:

* secure
* modular
* maintainable
* testable
* observable
* horizontally scalable
* model-independent

---

## 5. Technology

Target stack:

* Python 3.12+
* uv
* MCP Python SDK v2
* FastMCP where appropriate
* Pydantic
* httpx
* pytest
* ruff
* mypy
* Docker

---

## 6. Deployment

The platform must be container-friendly.

MCP servers should be independently deployable where practical.

The architecture must support deployment behind a load balancer.

---

## 7. Privacy

Customer information and ticket attachments must remain protected.

The platform must implement:

* least privilege
* RBAC
* data minimization
* PII filtering
* attachment controls
* secret protection
* audit logging

---

## 8. Development Rules

Development must use:

* mocked systems
* test data
* `.env.example`
* environment-based configuration

Real production credentials must not be committed.

Real customer attachments must not be placed in the repository.

---

## 9. Testing

Required:

* unit tests
* integration tests
* MCP contract tests
* security tests

Security-sensitive functionality requires dedicated tests.

---

## 10. Documentation

Architecture, security, MCP tools and significant design decisions must be documented.
