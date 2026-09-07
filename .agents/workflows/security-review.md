# Security Review

## Purpose

Perform a security review of a proposed or implemented change in the SuperOffice AI Support MCP Platform.

Security is a release requirement, not an optional improvement.

---

# Step 1 — Data Access

Identify:

* data accessed
* data returned
* data stored
* data sent to the AI
* data sent to external systems

Classify each data type according to:

```text
PUBLIC
INTERNAL
CONFIDENTIAL
RESTRICTED
SECRET
```

---

# Step 2 — Authentication

Verify:

* endpoint authentication
* identity propagation
* credential handling
* session/token handling

No hardcoded credentials.

---

# Step 3 — Authorization

Verify:

* RBAC
* tool-level permissions
* resource-level permissions where required
* deny-by-default behavior

Test unauthorized access.

---

# Step 4 — Data Minimization

Verify that the implementation returns only the minimum required data.

Check for unnecessary:

* customer fields
* PII
* ticket fields
* log content
* database records
* attachments

---

# Step 5 — PII

Search for exposure of:

* names
* email addresses
* phone numbers
* addresses
* identification numbers
* customer correspondence

Verify masking/redaction where appropriate.

---

# Step 6 — Secrets

Verify that implementation does not expose:

* passwords
* API keys
* OAuth tokens
* private keys
* database credentials
* connection strings

Check:

* source code
* logs
* errors
* tool output
* tests
* documentation

---

# Step 7 — Attachments

If attachments are involved, verify:

* authorization
* content-type validation
* size limits
* malware/security scanning where applicable
* DLP
* redaction
* access logging
* no automatic AI exposure

Attachments must remain deny-by-default.

---

# Step 8 — Database

Verify:

* read-only credentials
* query restrictions
* parameterized queries
* timeouts
* result limits
* dangerous statement rejection
* audit logging

Reject unrestricted SQL.

---

# Step 9 — Production Writes

If the feature writes data:

Verify:

* explicit authorization
* role permission
* input validation
* audit logging
* deterministic policy checks
* safe failure behavior

Destructive operations require additional controls.

---

# Step 10 — External AI Exposure

Determine whether information crosses the protected environment boundary.

If data is sent to an AI model:

Verify:

* minimum necessary data
* PII minimization
* secret removal
* attachment restrictions
* organizational policy compliance

---

# Step 11 — Logging

Verify logs do not contain:

* passwords
* tokens
* API keys
* private keys
* customer attachments
* unnecessary PII

Verify correlation IDs and audit events are present where required.

---

# Step 12 — Dependency Security

Review:

* new dependencies
* dependency versions
* unnecessary packages
* known security concerns

Do not add dependencies without justification.

---

# Step 13 — Tests

Require security tests for:

* unauthorized access
* privilege escalation
* PII exposure
* secret leakage
* attachment access
* SQL restrictions
* production write restrictions

---

# Step 14 — Verdict

Return one of:

```text
PASS
PASS WITH CONDITIONS
FAIL
```

For failures provide:

* issue
* severity
* affected component
* recommended fix

Do not mark the implementation secure merely because tests pass.
