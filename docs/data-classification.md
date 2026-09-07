# Data Classification

## Purpose

Define how information is handled before it is exposed through MCP or sent to an AI model.

---

# Level 0 — Public

Examples:

* public technical documentation
* public MCP documentation
* public Python documentation

### AI Access

Allowed.

---

# Level 1 — Internal

Examples:

* internal architecture
* internal SOPs
* internal runbooks
* internal development documentation

### AI Access

Allowed through authenticated MCP access.

---

# Level 2 — Confidential

Examples:

* ticket information
* internal application logs
* internal server information
* API diagnostic information
* database diagnostic information

### AI Access

Only when required for the investigation and authorized.

Prefer summaries and filtered results.

---

# Level 3 — Restricted

Examples:

* customer names
* email addresses
* phone numbers
* addresses
* identification information
* customer documents
* invoices
* screenshots
* PDFs
* images
* customer correspondence

### AI Access

Deny by default.

Access requires:

* authorization
* business purpose
* minimum necessary data
* DLP inspection
* redaction where possible
* audit logging

---

# Level 4 — Secret

Examples:

* passwords
* API keys
* OAuth tokens
* private keys
* database credentials
* connection strings
* session tokens

### AI Access

NEVER.

Secrets must never be returned by MCP tools.

---

# Data Handling Priority

Always prefer:

```text
No data
   ↓
Metadata
   ↓
Identifier
   ↓
Summary
   ↓
Redacted content
   ↓
Raw content
```

Move downward only when necessary.

---

# Attachment Classification

All customer-provided attachments should initially be treated as Level 3 Restricted.

This includes:

* PDF
* PNG
* JPG
* DOCX
* screenshots
* ZIP files
* exported reports

Attachments must not automatically become AI context.

---

# Log Classification

Logs should be treated as Level 2 by default.

If logs contain:

* PII
* credentials
* tokens
* customer content

the affected portion must be treated at the higher classification level.

---

# Database Classification

Database records must be classified according to their content.

Customer tables should normally be treated as Restricted.

Diagnostic metadata may be Confidential.

Credentials are Secret.

---

# AI Context Rule

Before data reaches the AI model:

```text
Classification
      ↓
Authorization
      ↓
Necessity
      ↓
Minimization
      ↓
Redaction
      ↓
AI
```

Never reverse this order.
