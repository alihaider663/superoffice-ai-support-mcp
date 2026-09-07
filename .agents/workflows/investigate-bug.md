# Investigate Bug

## Purpose

Provide a controlled and evidence-driven methodology for investigating a SuperOffice incident.

The workflow must minimize data exposure and avoid unnecessary tool calls.

---

# Step 1 — Understand the Problem

Identify:

* ticket ID
* reported symptom
* affected functionality
* reported time
* environment
* customer reference
* error message if available

Do not retrieve unnecessary customer information.

Do not automatically retrieve attachments.

---

# Step 2 — Establish Investigation Scope

Determine:

* exact incident window
* affected component
* affected environment
* affected user/customer scope
* reproducibility
* frequency

Use the smallest useful time window.

---

# Step 3 — Identify Correlation Data

Prioritize:

* ticket ID
* correlation ID
* request ID
* transaction ID
* API request ID
* timestamp
* node/server

Correlation identifiers should be used to connect evidence across systems.

---

# Step 4 — SuperOffice Evidence

Use SuperOffice MCP to retrieve only the information required to understand the issue.

Examples:

* ticket status
* ticket history
* relevant ticket events
* attachment metadata

Do not retrieve attachment content unless required and authorized.

---

# Step 5 — Application Evidence

Use Diagnostics MCP to search:

* application errors
* exceptions
* HTTP errors
* timeouts
* retries
* dependency failures

Use correlation IDs and time windows.

Avoid retrieving entire log files.

---

# Step 6 — API Evidence

Investigate:

* endpoint
* request timing
* HTTP status
* response time
* timeout
* downstream service
* correlation ID

---

# Step 7 — Database Evidence

Only investigate the database when evidence indicates a database-related problem.

Check:

* slow queries
* deadlocks
* blocking
* connection failures
* query errors

Use predefined diagnostic tools.

Never use unrestricted SQL.

---

# Step 8 — Infrastructure Evidence

Only investigate infrastructure when appropriate.

Check:

* node health
* CPU
* memory
* disk
* service status
* endpoint health
* load balancer
* network connectivity

Remember that SuperOffice is load-balanced.

Check for node-specific failures.

---

# Step 10 — Knowledge

Search the Knowledge MCP for:

* known issues
* runbooks
* previous incidents
* documented resolutions

Knowledge is supporting evidence, not proof.

---

# Step 11 — Correlate Evidence

Create a timeline:

```text
Time
 ↓
User action
 ↓
SuperOffice
 ↓
API
 ↓
Application
 ↓
Database
 ↓
Infrastructure
```

Identify where the failure first appears.

---

# Step 12 — Root Cause Classification

Classify conclusions as:

```text
CONFIRMED
PROBABLE
POSSIBLE
UNKNOWN
```

Never convert a hypothesis into a confirmed root cause without evidence.

---

# Step 13 — Final Investigation

Produce:

* problem summary
* timeline
* affected component
* evidence
* root cause
* confidence
* competing hypotheses
* validation
* recommended remediation
* next steps

---

# Security Requirements

Throughout the investigation:

* minimize PII
* do not expose secrets
* do not retrieve unnecessary attachments
* respect RBAC
* respect data classification
* do not execute destructive operations
* do not modify production without authorization

If required evidence cannot be accessed because of authorization restrictions, state that explicitly.

Do not bypass security controls.

---

# Completion

Before completing:

* validate evidence
* verify correlation
* identify uncertainty
* run security checks
* record relevant audit information

The final result must distinguish evidence from inference.
