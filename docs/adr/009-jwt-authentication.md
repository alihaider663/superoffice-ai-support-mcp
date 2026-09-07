# ADR 009 — JWT Bearer Token Authentication

## Status

Accepted

## Context

The MCP Gateway (ADR 008) requires an authentication mechanism to verify the identity of the AI agent (or any client) before processing MCP requests. The security model requires:

- All protected MCP endpoints must require authenticated access.
- Authentication mechanisms must be configurable.
- Credentials must never be hardcoded.
- Identity must propagate through the Gateway to backend MCP servers for audit logging.
- The mechanism must work with a stateless Gateway (ADR 004, ADR 008).

The `.env.example` establishes `AUTH_ENABLED=true` as the default but does not specify the mechanism.

## Decision

Use **JWT (JSON Web Token) Bearer tokens** for authentication at the MCP Gateway.

### Authentication Flow

```text
AI Agent
    │
    │  HTTP Header: Authorization: Bearer <JWT>
    ▼
MCP Gateway
    │
    ├── Extract Bearer token from Authorization header
    ├── Validate JWT signature (against configured signing key or JWKS)
    ├── Validate expiration (exp claim)
    ├── Validate issuer (iss claim) if configured
    ├── Validate audience (aud claim) if configured
    ├── Extract identity claims:
    │       • sub (subject / identity)
    │       • role (L1 | L2 | L3)
    │       • permissions (list of granted permissions)
    │       • production_write (boolean)
    │
    ├── Attach validated identity to request context
    │
    ▼
Authorization check (ADR 010)
    │
    ▼
Backend MCP Server (receives identity context for audit logging)
```

### JWT Claims (Conceptual)

```json
{
  "sub": "support-agent-01",
  "iss": "superoffice-ai-support",
  "aud": "mcp-gateway",
  "role": "L2",
  "permissions": [
    "superoffice:read",
    "diagnostics:read",
    "knowledge:read"
  ],
  "production_write": false,
  "iat": 1234567890,
  "exp": 1234567890
}
```

### Token Validation Configuration

| Setting | Development | Production |
|---------|------------|------------|
| Algorithm | HS256 (symmetric HMAC) | RS256 or ES256 (asymmetric) |
| Key source | `JWT_SECRET` env var | JWKS endpoint or public key file |
| Issuer validation | Optional | Required |
| Audience validation | Optional | Required |
| Expiration enforcement | Required | Required |

### Token Issuance

The Gateway **validates** tokens — it does not **issue** them.

| Environment | Token Source |
|------------|-------------|
| Development | Local CLI script or test fixture using the development signing key |
| Production | External identity provider, organizational auth service, or admin-issued service tokens |

This separation ensures the Gateway remains focused on enforcement. Token lifecycle management (issuance, rotation, revocation) is an external operational concern.

### Authentication Failure Responses

Failed authentication returns a structured error without leaking internal information:

```json
{
  "error": "authentication_failed",
  "message": "Invalid or expired token",
  "correlation_id": "abc-123"
}
```

The Gateway must not reveal whether the failure was due to an invalid signature, expired token, or missing claims — these details are logged internally for debugging but not exposed to the client.

## Alternatives Considered

### API Keys

Rejected. API keys are opaque identifiers that require a server-side lookup to determine the associated role and permissions. This introduces state (a key-to-identity mapping) that conflicts with the stateless Gateway design. API keys also lack a standardized way to carry structured claims (role, permissions) within the key itself.

### mTLS (Mutual TLS)

Rejected. mTLS provides strong cryptographic authentication but adds significant operational complexity: client certificate generation, distribution, rotation, and revocation. It does not natively carry role or permission information — an additional mechanism would be needed for RBAC claims. The operational overhead is disproportionate to the current deployment model.

### Full OAuth 2.0 Authorization Code Flow

Rejected. The AI agent is a service client, not a human user. The OAuth 2.0 authorization code flow (with redirects, consent screens, browser interaction) is designed for human-interactive authentication. For service-to-service communication, a pre-issued JWT (via client credentials grant or equivalent) is sufficient. The Gateway only needs to validate tokens, not manage the full OAuth dance.

### Session-Based Authentication

Rejected. Server-side sessions require session state storage, which conflicts with the stateless Gateway design (ADR 004, ADR 008). Session affinity (sticky sessions) would undermine horizontal scaling and load balancing.

## Consequences

### Positive

- Stateless — JWT is self-contained; no session or key lookup required at request time.
- Standard — Bearer token authentication is widely supported by HTTP clients and AI agent frameworks.
- Claims-based — role and permission information travels with the token, enabling immediate authorization without additional lookups.
- Configurable — switching from development (HMAC) to production (RSA/ECDSA, JWKS) requires only configuration changes, no code changes.
- Identity propagation — the Gateway extracts claims and passes identity context to backend MCP servers for audit logging.

### Negative

- Token revocation — JWTs cannot be individually revoked before expiration without a revocation list (which introduces state). Mitigation: use short-lived tokens (e.g., 1 hour) and rely on expiration.
- Signing key management — the signing key (or JWKS endpoint) must be securely managed. In production, this should use a secret management solution (Open Decision 6 in ADR 006).
- Token size — JWTs with many claims can become large. For this platform's simple role model, this is not a concern.

### Risks

- Compromised signing key — if the JWT signing key is leaked, an attacker can forge tokens with any role. Mitigation: use asymmetric keys in production (the private key is used only by the token issuer, not by the Gateway which uses only the public key for validation).
- Clock skew — JWT expiration validation is sensitive to clock differences between the token issuer and the Gateway. Mitigation: use standard NTP synchronization and allow a small clock skew tolerance.
