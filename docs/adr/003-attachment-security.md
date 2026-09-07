# ADR 003 — Attachment Security

## Status

Accepted

## Context

SuperOffice tickets may contain customer-provided attachments including PDFs, PNGs, JPGs, DOCX files, screenshots, ZIP files, and exported reports. These attachments may contain:

- Customer PII (names, addresses, identification numbers)
- Business-confidential content (invoices, contracts, internal documents)
- Credentials or tokens (screenshots of configuration, exported reports)
- Malicious content (malware, embedded scripts)

Automatically sending attachments to an AI model would constitute uncontrolled data exfiltration from the protected application boundary. The project documentation classifies all customer-provided attachments as Level 3 — Restricted.

## Decision

Attachments are deny-by-default.

### Default Behavior

- Attachment **metadata** (filename, size, type, timestamp) may be returned to the AI when authorized.
- Attachment **content** must never be automatically returned to the AI.
- The `.env.example` establishes `ATTACHMENT_ACCESS_ENABLED=false` as the default configuration.

### Access Pipeline

When attachment content is required for an investigation, the following pipeline must be enforced:

```text
AI requests attachment
  → Authorization (RBAC role check)
  → Purpose validation (is attachment relevant to the investigation?)
  → Attachment policy (content-type allowlist, size limits)
  → Security inspection (malware/content scanning where applicable)
  → DLP / redaction (PII and secret removal)
  → Minimum required content
  → AI
```

### Controls

- Content-type validation against an allowlist.
- Size limits to prevent excessively large payloads.
- DLP inspection for PII and secrets within attachment content.
- Redaction of identified sensitive content where possible.
- Audit logging of every attachment access with correlation ID, identity, and purpose.
- No automatic AI exposure — the AI may list and inspect metadata, but content requires explicit authorization.

## Alternatives Considered

### Allow Attachments by Default

Rejected. Unacceptable risk. Customer attachments are Level 3 Restricted and may contain PII, credentials, or malicious content. Automatic exposure to an external AI provider violates data minimization principles.

### Deny Attachments Entirely (No Content Access Ever)

Rejected. Would severely limit L3 investigation capability. Some incidents require reviewing screenshots, error exports, or configuration documents. The controlled pipeline provides secure access when genuinely needed.

### AI-Based Attachment Filtering

Rejected. The AI cannot be trusted to determine whether attachment content should be exposed — this is a circular dependency. Attachment access decisions must be made by deterministic security code before content reaches the model.

## Consequences

### Positive

- Customer attachments are protected by default.
- Explicit audit trail for every attachment access.
- DLP and redaction are applied before content reaches the AI.
- Malicious attachment content does not automatically reach the AI context.

### Negative

- L1 and L2 investigations cannot access attachment content without elevated authorization.
- Attachment processing pipeline adds latency and implementation complexity.
- DLP/redaction for binary formats (PDF, images) requires additional tooling.
- Some legitimate investigation needs may be blocked by overly restrictive policies until roles are properly assigned.

### Risks

- Incomplete DLP — binary formats are difficult to fully scan for embedded PII or secrets.
- Scanning mechanism is an open decision — the specific malware/content scanning technology has not been selected.
- Image-based attachments (PNG, JPG, screenshots) may contain text that is not detected without OCR.
