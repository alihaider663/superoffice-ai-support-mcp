# Implement Feature

## Purpose

Safely implement a new feature in the SuperOffice AI Support MCP Platform while preserving the existing architecture, security model and testing standards.

## Procedure

### Step 1 — Understand

Read:

* `.agents/rules/`
* `docs/project-requirements.md`
* `docs/architecture.md`
* `docs/security-model.md`
* relevant server responsibility documentation

Inspect the existing repository before making changes.

Do not assume the requested feature belongs in the current module.

---

### Step 2 — Classify

Determine:

* Which architectural layer owns the feature?
* Which MCP server owns the capability?
* Is this business logic?
* Is this an external integration?
* Does it require a new service?
* Does it require a new security policy?
* What data classification is involved?

Do not implement cross-domain functionality directly inside an MCP tool.

---

### Step 3 — Plan

Before coding, produce a concise implementation plan containing:

* files to create/change
* architectural layer
* dependencies
* security implications
* test strategy
* documentation changes

For significant architectural changes, create or update an ADR.

---

### Step 4 — Implement

Implement the smallest coherent change.

Follow existing patterns.

Use:

* typed Pydantic models
* type hints
* async I/O where appropriate
* dependency injection
* structured logging
* typed exceptions

Keep MCP tool handlers thin.

---

### Step 5 — Security Review

Check:

* authentication
* authorization
* RBAC
* data minimization
* PII
* secrets
* attachment handling
* SQL restrictions
* production writes

Never add a security bypass for convenience.

---

### Step 6 — Tests

Add or update:

* unit tests
* integration tests where appropriate
* MCP contract tests
* security tests

Every new security-sensitive capability must have a security test.

---

### Step 7 — Validation

Run appropriate:

```text
ruff
mypy
pytest
```

Fix failures before completing the task.

---

### Step 8 — Documentation

Update relevant:

* architecture documentation
* MCP tool documentation
* security documentation
* ADRs

---

### Step 9 — Final Report

Report:

* what changed
* files changed
* tests executed
* security considerations
* documentation updated
* remaining risks

Do not make unrelated changes.
