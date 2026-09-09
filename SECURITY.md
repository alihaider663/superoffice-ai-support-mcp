# Security Policy

## Scope & Supported Versions

This repository contains the **SuperOffice AI Support MCP Platform**.

| Version | Release Type | Supported | Notes |
| :--- | :--- | :---: | :--- |
| `v1.0.0-local.1` | Local Development Release 1.0 | :white_check_mark: | Active baseline for local development and architecture evaluation |
| `< 1.0.0` | Pre-release gates | :x: | Historical development milestones |

> [!WARNING]
> **Production Boundary Disclaimer**
> 
> Current releases (including `v1.0.0-local.1`) are designed, implemented, and verified **strictly for local development, offline testing, and architecture evaluation**. They do not claim production operational deployment, production network trust, high availability, disaster recovery, or integration with enterprise secret managers.

---

## Reporting a Security Vulnerability

We take the security of the platform and customer CRM data seriously. If you discover or suspect a security vulnerability or potential credential exposure:

1. **Do NOT open a public issue or pull/merge request** containing details of the vulnerability, potential exploit payloads, or sensitive information.
2. **Do NOT commit credentials, tokens, or customer data** to version control under any circumstances.
3. **Contact Channel**: Please contact the repository maintainers directly via the private communication channel established for this repository (configured upon remote publication). If using a hosted repository provider that supports private vulnerability reporting, utilize the private vulnerability disclosure feature.
4. **Information to Include**:
   - Component / server affected (Gateway, SuperOffice MCP, Diagnostics MCP, Knowledge MCP, Investigation MCP, Security library).
   - Type of vulnerability (e.g., authorization bypass, prompt injection, PII leak, credential leakage, SSRF, SQL injection).
   - Clear, reproducible steps or a proof of concept (using synthetic test data only; never production CRM data).
   - Potential impact on the system or data confidentiality.

---

## Core Security Architecture & Invariants

The platform enforces strict defense-in-depth boundaries:

1. **Zero Direct AI Backend Access**: External AI reasoning engines and LLMs have zero direct access to databases, filesystems, attachments, operating system shells, or enterprise credentials. All operations are mediated through the MCP Gateway.
2. **Deny-by-Default Authorization (RBAC)**: All tool requests require valid JWT authentication. Unmapped roles, unknown tools, or unauthenticated requests are rejected immediately.
3. **Database Query Constraints**:
   - Hard execution timeout capped at 5.0 seconds (Decision D01).
   - Result row count capped at 50 rows (Decision D02).
   - Mandatory `SNAPSHOT` transaction isolation (Decision D09). Zero dynamic or arbitrary SQL execution.
4. **Attachment Content Protection (Decision D05)**: Attachment downloads and raw file ingestion into LLMs are denied by default. Only metadata is accessible via the `list_attachments` tool.
5. **Customer Data Boundary (Decision D08)**: Live production transmission of confidential/sensitive SuperOffice CRM data to external AI endpoints is unapproved.
6. **Data Minimization & Egress Sanitization**: All responses pass through automated PII, token, and secret scrubbing filters before delivery.

---

## Credential & Secret Exposure Response

If a secret, API key, token, or password is accidentally committed:
- It must be considered compromised immediately and rotated in the upstream system.
- The commit or branch must be reported to repository maintainers for controlled remediation.
