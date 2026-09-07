# Security Model

## 1. Security Objective

The SuperOffice AI Support MCP Platform must allow AI-assisted troubleshooting without unnecessarily exposing confidential enterprise or customer information to the AI model.

Security must be enforced by deterministic application code.

The AI model must never be considered a security boundary.

---

## 2. Defense in Depth

Security controls must exist at multiple layers:

```text
Authentication
      ↓
Authorization
      ↓
RBAC
      ↓
Tool Permission
      ↓
Data Classification
      ↓
DLP / PII Filtering
      ↓
Attachment Policy
      ↓
Audit Logging
      ↓
AI
```

---

## 3. Authentication

All protected MCP endpoints must require authenticated access.

Authentication mechanisms must be configurable.

Credentials must never be hardcoded.

---

## 4. Authorization

Authorization must be evaluated before executing protected tools.

Use least privilege.

A user must only receive access to tools and data required by their role.

---

## 5. RBAC

Initial conceptual roles:

### L1

Basic ticket investigation.

Allowed:

* ticket summary
* ticket status
* basic knowledge search

Restricted:

* customer details
* attachments
* infrastructure
* database diagnostics

### L2

Extended technical investigation.

Allowed:

* L1 capabilities
* application logs
* API diagnostics
* integration diagnostics
* selected database diagnostics

### L3

Advanced technical investigation.

Allowed:

* L2 capabilities
* advanced diagnostics
* infrastructure diagnostics
* approved attachment analysis

Production write operations remain separately controlled.

---

## 6. Data Minimization

The platform must return the minimum information necessary.

Prefer:

```text
identifier
>
metadata
>
summary
>
redacted content
>
raw content
```

Raw content should only be returned when required.

---

## 7. PII

Potential PII includes:

* name
* email
* phone number
* address
* identification numbers
* customer account information
* personal correspondence

PII must be:

* avoided where unnecessary
* masked where possible
* returned only when authorized and required

---

## 8. Secrets

Never expose:

* passwords
* API keys
* OAuth tokens
* private keys
* database credentials
* connection strings
* authentication cookies

If secrets appear inside logs or attachments, redact them.

Never log secrets.

---

## 9. Attachments

Attachments are deny-by-default.

Supported examples:

* PDF
* PNG
* JPG
* DOCX
* screenshots

The system must not automatically send attachments to the AI.

Access flow:

```text
AI requests attachment
        ↓
Authorization
        ↓
Purpose validation
        ↓
Attachment policy
        ↓
Security inspection
        ↓
DLP / redaction
        ↓
Minimum required content
        ↓
AI
```

---

## 10. Database Security

Database access must be read-only by default.

Prefer predefined diagnostic tools.

Never provide unrestricted SQL execution.

Enforce:

* read-only credentials
* query validation
* query timeout
* result limits
* auditing

Dangerous statements must be rejected.

---

## 11. Production Writes

Production modifications require:

* authentication
* authorization
* explicit permission
* validation
* audit logging
* deterministic policy approval

Destructive operations should not be automatically performed by the AI.

---

## 12. Logging

Audit logs should capture:

* correlation ID
* authenticated identity
* MCP server
* tool
* authorization result
* timestamp
* downstream dependency
* result status

Never log:

* passwords
* tokens
* API keys
* private keys
* full sensitive attachments

---

## 13. External AI Provider

Any information intentionally returned to an external AI provider must be treated as data leaving the protected application boundary.

Therefore:

* minimize data
* redact unnecessary PII
* remove secrets
* avoid raw attachments
* prefer summaries

If organizational policy requires that customer data never leaves the organization's environment, use an appropriate private/self-hosted model or enterprise deployment model.

---

## 14. Security Principle

The system must follow:

> The AI receives only the minimum information required to solve the problem.

---

## 15. Backend Network & Downstream Trust Boundary

1. **Mandatory Backend Reachability Invariant**:
   - Backend MCP Streamable HTTP endpoints MUST NOT be directly reachable from AI clients or untrusted networks.
   - External MCP clients communicate only with the Gateway.
   - Gateway → backend MCP communication occurs through the trusted internal service network.
   - Deployment/network controls must prevent direct client access to backend MCP server ports.
   - The Gateway is the approved external ingress/security perimeter.

2. **Downstream Trust Model**:
   - Gateway-generated identity and privilege headers (`X-User-ID`, `X-User-Role`, `X-Production-Write`, `X-Attachment-Access`, `X-Correlation-ID`) are trusted internal transport context derived exclusively from validated Gateway `SecurityContext`.
   - They are not cryptographically signed identity assertions.

3. **DNS Rebinding Protection Scope**:
   - `TransportSecuritySettings` / `allowed_hosts` provide DNS rebinding and Host-Origin header protection at the backend FastMCP server edge.
   - They do not provide authentication or authorization; JWT authentication and RBAC authorization remain owned by the Gateway.
   - Network and deployment controls prevent direct backend bypass.
