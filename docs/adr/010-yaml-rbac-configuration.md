# ADR 010 — Declarative YAML RBAC Configuration

## Status

Accepted

## Context

The security model defines three role tiers for AI-assisted support:

- **L1** — Basic ticket investigation (ticket summary, status, basic knowledge search)
- **L2** — Extended technical investigation (L1 + application logs, API diagnostics, selected DB diagnostics)
- **L3** — Advanced technical investigation (L2 + infrastructure, advanced DB diagnostics, approved attachment analysis)

Production write operations are separately controlled — they are not a role level but an orthogonal permission.

The MCP Gateway (ADR 008) must evaluate these roles against per-tool permissions at every request. The authorization decision must be deterministic, enforced in code, and never delegated to the AI model (security model principle).

## Decision

Use **declarative YAML-based tool permission configuration** loaded by the MCP Gateway at startup.

### Permission Model

```text
JWT role claim (L1 | L2 | L3)
    │
    ▼
Gateway loads tool_permissions.yaml
    │
    ▼
Lookup tool entry by server + tool name
    │
    ▼
Check: role ≥ tool.minimum_role?
    │
    ├── No  → 403 Forbidden (audit logged)
    │
    ├── Yes → Check additional permission flags
    │            │
    │            ├── tool.requires contains "production_write"?
    │            │       → Check JWT production_write == true
    │            │
    │            ├── tool.requires contains "attachment_access"?
    │            │       → Check JWT + ATTACHMENT_ACCESS_ENABLED
    │            │
    │            └── All checks pass → Proxy to backend
    │
    ▼
Audit log: identity, tool, authorization decision, reason
```

### Role Hierarchy

Roles are cumulative. Higher tiers inherit all lower-tier permissions:

```text
L3 ⊇ L2 ⊇ L1
```

This means an L3 role can access any tool that requires L1 or L2.

### Tool Classification

Every MCP tool is classified with:

| Field | Purpose |
|-------|---------|
| `minimum_role` | Minimum role required to invoke the tool (L1, L2, L3) |
| `classification` | Side-effect classification (READ_ONLY, SAFE_WRITE, SENSITIVE_WRITE, DESTRUCTIVE) |
| `data_level` | Data classification level (PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED, SECRET) |
| `requires` | Additional permission flags beyond the role (e.g., `production_write`, `attachment_access`) |

### Configuration Schema (Conceptual)

```yaml
# tool_permissions.yaml

superoffice_mcp:
  get_ticket:
    minimum_role: L1
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  search_tickets:
    minimum_role: L1
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  get_ticket_history:
    minimum_role: L1
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  get_ticket_status:
    minimum_role: L1
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  get_customer:
    minimum_role: L2
    classification: READ_ONLY
    data_level: RESTRICTED

  get_person:
    minimum_role: L2
    classification: READ_ONLY
    data_level: RESTRICTED

  list_attachments:
    minimum_role: L1
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  get_attachment_metadata:
    minimum_role: L1
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  get_attachment_content:
    minimum_role: L3
    classification: READ_ONLY
    data_level: RESTRICTED
    requires:
      - attachment_access

  add_ticket_note:
    minimum_role: L2
    classification: SAFE_WRITE
    requires:
      - production_write

  add_ticket_reply:
    minimum_role: L2
    classification: SAFE_WRITE
    requires:
      - production_write

  update_ticket:
    minimum_role: L2
    classification: SENSITIVE_WRITE
    requires:
      - production_write

diagnostics_mcp:
  search_application_logs:
    minimum_role: L2
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  search_api_logs:
    minimum_role: L2
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  find_http_errors:
    minimum_role: L2
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  find_timeout_errors:
    minimum_role: L2
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  find_slow_queries:
    minimum_role: L2
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  find_deadlocks:
    minimum_role: L3
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  find_blocking_sessions:
    minimum_role: L3
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  correlate_transaction:
    minimum_role: L2
    classification: READ_ONLY
    data_level: CONFIDENTIAL

knowledge_mcp:
  search_knowledge:
    minimum_role: L1
    classification: READ_ONLY
    data_level: INTERNAL

  get_runbook:
    minimum_role: L1
    classification: READ_ONLY
    data_level: INTERNAL

  find_known_issue:
    minimum_role: L1
    classification: READ_ONLY
    data_level: INTERNAL

  search_previous_incidents:
    minimum_role: L1
    classification: READ_ONLY
    data_level: INTERNAL

  get_resolution_pattern:
    minimum_role: L1
    classification: READ_ONLY
    data_level: INTERNAL

infrastructure_mcp:
  get_server_health:
    minimum_role: L3
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  get_cpu_usage:
    minimum_role: L3
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  get_memory_usage:
    minimum_role: L3
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  get_disk_usage:
    minimum_role: L3
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  get_service_status:
    minimum_role: L3
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  check_endpoint:
    minimum_role: L3
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  test_tcp_connection:
    minimum_role: L3
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  check_load_balancer:
    minimum_role: L3
    classification: READ_ONLY
    data_level: CONFIDENTIAL

  get_node_health:
    minimum_role: L3
    classification: READ_ONLY
    data_level: CONFIDENTIAL
```

### Default Behavior

If a tool is invoked that does not appear in the configuration, the Gateway **denies the request** (deny-by-default, consistent with ADR 002). Every tool must be explicitly registered in the permission configuration to be accessible.

### Configuration Validation

The Gateway validates the tool permission configuration at startup:

- All referenced roles must be valid (L1, L2, L3)
- All classifications must be valid (READ_ONLY, SAFE_WRITE, SENSITIVE_WRITE, DESTRUCTIVE)
- All data levels must be valid (PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED, SECRET)
- Write-classified tools must have `production_write` in their requires list
- Duplicate tool entries are rejected

Invalid configuration prevents the Gateway from starting. This ensures configuration errors are caught at deployment time, not at request time.

## Alternatives Considered

### Policy Engine (OPA / Cedar)

Rejected for the current scope. The RBAC model has 3 role tiers, approximately 30 tools, and a simple hierarchical permission structure. A dedicated policy engine (separate service, separate policy language, separate deployment) adds infrastructure complexity that is disproportionate to the current model's simplicity. If the model grows significantly more complex (e.g., resource-level permissions, conditional policies, multi-tenant isolation), a policy engine can be adopted later — the Gateway's authorization check is an internal implementation detail that can be swapped without architectural disruption.

### Database-Backed Role Management

Rejected. Database-backed role management is appropriate when roles change frequently at runtime or are managed by a separate admin UI. Support tier assignments (L1/L2/L3) change infrequently and align with organizational role definitions. YAML configuration is simpler, faster (no DB round trip), and more transparent. It is also version-controlled alongside the code.

### Hardcoded Permissions in Code

Rejected. Embedding permission rules directly in the Gateway code makes them harder to review, harder to change without code deployment, and harder to test independently. YAML externalizes the policy from the enforcement logic, enabling configuration changes without code changes.

### External Identity Provider Role Mapping

Not rejected but deferred. In production, roles may originate from an external identity provider (e.g., Azure AD groups mapped to L1/L2/L3). This is compatible with the current design — the JWT token carries the role claim regardless of where the role was assigned. The YAML configuration defines what each role can do; the token defines which role the identity has. These are orthogonal concerns.

## Consequences

### Positive

- Deterministic — authorization decisions are based on static configuration, not AI reasoning.
- Testable — the permission configuration can be validated by unit tests (e.g., "L1 cannot access infrastructure tools").
- Auditable — YAML is human-readable and reviewable in code review and pull requests.
- Version-controlled — permission changes are tracked in git history.
- Deny-by-default — unregistered tools are automatically denied.
- Startup validation — configuration errors are caught before the Gateway accepts requests.
- Separation of concerns — the YAML defines the policy; the Gateway enforces it; the JWT carries the identity.

### Negative

- Static — adding a new tool requires updating the YAML and redeploying the Gateway.
- No runtime role changes — changing a user's role requires issuing a new JWT.
- Limited expressiveness — cannot express complex conditional policies (e.g., "allow only during business hours"). The current requirements do not need this.

### Risks

- Configuration drift — the tool permission YAML must stay synchronized with the actual tools registered in each MCP server. Mitigation: MCP contract tests should verify that every registered tool has a corresponding permission entry.
- Overly permissive initial configuration — during development, there may be temptation to set all tools to L1. Mitigation: code review and security review workflow enforcement.
