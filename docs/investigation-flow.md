# Investigation Flow

## 1. Objective

Provide a controlled methodology for investigating SuperOffice incidents using evidence from multiple systems.

The AI must investigate systematically rather than blindly calling every available MCP tool.

---

# 2. Investigation Lifecycle

```text
Ticket
  ↓
Problem Definition
  ↓
Scope
  ↓
Time Window
  ↓
Correlation Identifier
  ↓
SuperOffice Evidence
  ↓
Application Evidence
  ↓
API Evidence
  ↓
Database Evidence
  ↓
Infrastructure Evidence
  ↓
Knowledge Evidence
  ↓
Evidence Correlation
  ↓
Hypothesis
  ↓
Validation
  ↓
Root Cause Classification
  ↓
Recommendation
```

---

# 3. Step 1 — Understand the Ticket

Extract:

* ticket ID
* subject
* description
* status
* timestamps
* affected functionality
* reported symptoms

Do not automatically retrieve attachments.

Do not automatically retrieve unnecessary customer information.

---

# 4. Step 2 — Establish Scope

Determine:

* affected customer or customer reference
* affected environment
* affected application
* affected component
* approximate incident time
* frequency
* whether issue is reproducible

---

# 5. Step 3 — Identify Correlation Data

Look for:

* ticket ID
* request ID
* correlation ID
* transaction ID
* timestamp
* API endpoint
* error code

Correlation IDs should be prioritized whenever available.

---

# 6. Step 4 — Investigate Application

Search application logs around the relevant time window.

Look for:

* exceptions
* HTTP errors
* timeouts
* retries
* dependency failures

Do not retrieve entire log files unnecessarily.

---

# 7. Step 5 — Investigate APIs

Check:

* endpoint
* HTTP status
* response time
* timeout
* request correlation
* downstream dependency

---

# 8. Step 6 — Investigate Database

Only when evidence suggests a database issue.

Check:

* slow queries
* deadlocks
* blocking
* connection problems
* query execution failures

Use read-only diagnostics.

---

# 9. Step 7 — Investigate Infrastructure

Only when evidence indicates an infrastructure issue.

Check:

* CPU
* memory
* disk
* service health
* endpoint availability
* load balancer health
* node-specific failures

---

# 11. Load-Balanced Environment

SuperOffice is deployed in a load-balanced environment.

Do not assume a problem exists on every node.

Correlate:

* timestamp
* request
* node
* load balancer
* application logs

A node-specific failure must be considered separately.

---

# 12. Knowledge Validation

Use the knowledge base to identify:

* known issues
* previous incidents
* standard troubleshooting procedures
* documented fixes

Knowledge results are supporting evidence.

They do not automatically prove the current root cause.

---

# 13. Evidence Classification

Every important finding should be classified as:

```text
CONFIRMED
PROBABLE
POSSIBLE
UNKNOWN
```

Never present a probable hypothesis as confirmed.

---

# 14. Root Cause Output

A final investigation should contain:

* problem summary
* affected component
* root cause classification
* supporting evidence
* confidence
* competing hypotheses
* validation performed
* recommended remediation
* next steps

---

# 15. Investigation Safety

The AI must:

* minimize data access
* respect authorization
* avoid unnecessary attachments
* avoid secrets
* avoid unrestricted SQL
* avoid destructive operations
* avoid modifying production without authorization

If evidence is insufficient, report uncertainty instead of inventing a conclusion.

---

# 16. L1 / L2 / L3 Escalation

### L1

Focus on:

* ticket understanding
* basic status
* known solutions
* standard runbooks
* basic diagnostics

### L2

Focus on:

* application logs
* API diagnostics
* integrations
* database symptoms
* correlation analysis

### L3

Focus on:

* deep cross-system correlation
* advanced database diagnostics
* infrastructure
* node-specific behavior
* root-cause validation

Escalation must be evidence-driven.
