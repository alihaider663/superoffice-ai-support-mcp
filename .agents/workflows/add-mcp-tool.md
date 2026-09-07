# Add MCP Tool

## Purpose

Safely design and implement a new MCP tool while maintaining clear server boundaries, security controls and model-friendly interfaces.

---

## Step 1 — Identify Ownership

Determine which MCP server owns the capability:

* SuperOffice MCP
* Diagnostics MCP
* Knowledge MCP
* Infrastructure MCP

Do not add the tool to a server simply because it is convenient.

If ownership is unclear, stop and explain the architectural conflict.

---

## Step 2 — Define Purpose

Document:

* tool name
* purpose
* server
* input
* output
* data accessed
* side effects
* required permissions
* data classification

The tool description must clearly explain what it does and what it does not do.

---

## Step 3 — Define Input

Use strongly typed Pydantic models.

Validate:

* identifiers
* dates
* time ranges
* limits
* filters
* pagination
* optional parameters

Reject invalid or dangerous input.

Avoid arbitrary free-form inputs when structured inputs are possible.

---

## Step 4 — Define Output

Return only information required for the task.

Prefer structured output.

Use:

* typed response models
* concise fields
* explicit status
* relevant evidence
* warnings where applicable

Do not return unnecessary customer data.

Do not return secrets.

Do not return raw attachments unless explicitly authorized.

---

## Step 5 — Security

Determine:

* authentication requirement
* RBAC role
* tool permission
* data classification
* PII exposure
* DLP requirements
* audit requirements

Security must be enforced in deterministic code.

Never rely on the LLM to enforce authorization.

---

## Step 6 — Architecture

Use:

```text
MCP Tool
    ↓
Application Service
    ↓
Integration Client
    ↓
External System
```

Do not put external API/database logic directly inside the MCP tool unless the operation is genuinely trivial and follows existing project conventions.

---

## Step 7 — Side Effects

Explicitly classify the tool:

```text
READ_ONLY
SAFE_WRITE
SENSITIVE_WRITE
DESTRUCTIVE
```

Default to READ_ONLY.

Writes require explicit authorization.

Destructive operations require stronger controls and must never be implicitly triggered by an AI investigation.

---

## Step 8 — Errors

Use predictable typed errors.

Do not expose:

* stack traces
* credentials
* connection strings
* internal secrets

Return useful but safe diagnostic information.

---

## Step 9 — Tests

Create:

* successful execution test
* invalid input test
* authorization test
* data filtering test
* error handling test

For write operations also test:

* unauthorized write
* invalid state
* audit event
* policy rejection

---

## Step 10 — Documentation

Update the MCP tool documentation with:

* name
* purpose
* input schema
* output schema
* permissions
* data classification
* side effects
* examples
* failure conditions

---

## Step 11 — Final Verification

Run:

```text
ruff
mypy
pytest
```

Verify that no unrelated files were changed.

Report the completed tool and its security classification.
