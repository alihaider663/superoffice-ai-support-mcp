# ADR 002 — Deny-by-Default Data Access

## Status

Accepted

## Context

The platform operates on confidential enterprise data including customer information, ticket content, application logs, database records, attachments, and infrastructure details. An AI model receiving this data represents data leaving the protected application boundary.

Without explicit controls, the default behavior of MCP tools would be to return all available data to the AI. This creates unacceptable risk: customer PII exposure, secret leakage, unnecessary data in AI provider context windows, and potential regulatory violations.

The project documentation establishes a clear principle: "The existence of data does not imply permission to expose that data to the AI."

## Decision

All data access is deny-by-default.

Data must pass through a classification, authorization, and minimization pipeline before reaching the AI:

```text
Classification → Authorization → Necessity → Minimization → Redaction → AI
```

### Data Classification Levels

| Level | Classification | AI Access |
|-------|---------------|-----------|
| 0 | Public | Allowed |
| 1 | Internal | Allowed through authenticated MCP |
| 2 | Confidential | Only when required and authorized; prefer summaries |
| 3 | Restricted | Deny by default; requires authorization + purpose + DLP + audit |
| 4 | Secret | NEVER |

### Data Handling Priority

Always prefer the minimum exposure level:

```text
No data > Metadata > Identifier > Summary > Redacted content > Raw content
```

### Enforcement

- Security is enforced in deterministic application code, never by the LLM.
- PII must be minimized or redacted where possible.
- Secrets must never be returned by MCP tools.
- Logs containing PII, credentials, or tokens are elevated to the higher classification level.
- Database records are classified according to their content.

## Alternatives Considered

### Allow-by-Default with Filtering

Rejected. Fundamentally inverts the security model. Requires enumerating everything to block rather than explicitly granting access. Inevitably leads to data leakage through omission.

### Per-Tool Data Classification Only

Rejected. Insufficient granularity. A single tool may access data at multiple classification levels (e.g., a log search tool may return Level 2 logs that contain Level 4 credentials). Classification must be applied at the data level, not only the tool level.

### AI-Enforced Data Controls

Rejected. The AI model is explicitly excluded as a security boundary. LLMs cannot reliably enforce data classification. All controls must be deterministic code.

## Consequences

### Positive

- Customer data is protected by default.
- Secrets are structurally prevented from reaching the AI.
- PII exposure is minimized.
- Regulatory risk is reduced.
- Clear audit trail of what data was exposed and why.

### Negative

- Development velocity is reduced — every tool must implement classification and filtering.
- Some investigations may require multiple tool calls to progressively access data.
- Redaction logic must be maintained and tested.
- Overly aggressive redaction could reduce investigation effectiveness.

### Risks

- Incomplete redaction — PII or secrets may appear in unexpected fields (e.g., embedded in log messages or error text).
- Classification drift — new data sources may not be immediately classified.
- Developer bypass — convenience shortcuts during development could weaken controls if not caught in review.
