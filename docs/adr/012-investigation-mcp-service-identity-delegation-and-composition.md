# ADR 012 — Investigation MCP Service Identity, Delegation & Composition Architecture

## Status

Accepted (Phase 4.1 Architecture Gate)

## Context

Phase 3 established the Layer-3 generic investigation engine (`platform_investigation`) and Layer-4 application service orchestration (`platform_investigation_service`). To expose cross-domain incident investigation capabilities to AI clients via the Model Context Protocol (MCP), an architectural host and composition runtime is required.

In the platform topology, the Gateway (Layer 2) enforces perimeter security (Bearer JWT authentication, YAML-based RBAC, rate limiting, and output sanitization). Downstream MCP servers (`so-mcp`, `diag-mcp`, `kb-mcp`) execute domain capabilities over Streamable HTTP on an internal network.

Introducing an investigation runtime introduces a cross-domain service-to-service orchestration path:
```text
External Client
      ↓ (Streamable HTTP / Bearer JWT)
   Gateway (Layer 2)
      ↓ (Streamable HTTP / Perimeter Auth)
investigation-mcp (Layer 1 / Layer 4 Host)
      ↓ (Streamable HTTP / Second Hop)
SuperOffice MCP / Diagnostics MCP
```

This second hop (`investigation-mcp` → backend MCP) requires explicit architectural governance regarding service identity, authorization delegation, network trust boundaries, and composite RBAC semantics.

---

## Decisions

### 1. Dedicated Investigation Runtime
The investigation runtime is deployed as a dedicated, fault-isolated FastMCP microservice (`investigation-mcp`) exposing `/mcp` over Streamable HTTP. It is not embedded inside `so-mcp` or `diag-mcp` (which would violate domain boundaries) nor inside the Gateway (which would violate Layer-2 / Layer-4 separation).

### 2. Official Streamable HTTP Composition
`investigation-mcp` satisfies domain service ports (`SuperOfficeServicePort`, `DiagnosticsServicePort`) by calling `so-mcp` and `diag-mcp` over Streamable HTTP using the official MCP Python SDK (`streamable_http_client` and `ClientSession`). No direct database access, raw REST APIs, or disk/attachment systems are accessed.

### 3. Network-Bound Caller Authorization Prerequisite
The platform uses a **Network-Policy-Bound Trusted Service Path** for internal service-to-service communication.
- **Production Prerequisite**: Backend MCP endpoints (`so-mcp`, `diag-mcp`, `kb-mcp`) must be restricted by infrastructure network policy (e.g. Kubernetes `NetworkPolicy`, private VPC subnet firewall rules) so that only authorized workloads (`gateway`, `investigation-mcp`) can reach them.
- **Production Enablement Boundary**: Live production second-hop traffic is **BLOCKED** until this network policy enforcement is provisioned and verified in deployment infrastructure. Local development and automated tests are authorized using synthetic/mocked fixtures.

### 4. No Cryptographic Workload Identity Claim
Service identity on the second hop is enforced strictly through network-bound caller connectivity restrictions. No mTLS, SPIFFE certificates, or custom HMAC tokens are claimed or assumed in application code.

### 5. Centralized RBAC Authority
The Gateway remains the **sole and exclusive authorization authority**.
- Backend MCP servers do not evaluate JWTs or enforce tool RBAC.
- `investigation-mcp` contains zero RBAC YAML parsing, zero role comparisons, and zero subordinate authorization logic.

### 6. L3 Composite Baseline
The public composite tool `investigate_incident` is authorized at **`minimum_role: L3`** (`classification: READ_ONLY`, `data_level: CONFIDENTIAL`) at the Gateway perimeter.
- Under the currently approved subordinate capability set and current RBAC policy, the L3 composite minimum role prevents role-based privilege amplification.
- L2 reduced-capability investigation profiles are deferred to a separate future capability design.

### 7. Frozen Subordinate Capability Set
The initial Phase 4 investigation tool is strictly hard-bounded to invoke only four subordinate backend operations:
1. `get_ticket` (SuperOffice MCP)
2. `get_database_health` (Diagnostics MCP)
3. `find_slow_queries` (Diagnostics MCP)
4. `find_deadlocks` (Diagnostics MCP)

All other tools (ticket messages, attachments, blocking sessions, ticket diagnostic records, logs, Knowledge, Infrastructure) are explicitly excluded from the Phase 4 baseline.

### 8. Composite Permission Drift Regression
Automated architecture and security regression tests must enforce that the composite tool's role and data level remain at least as restrictive as every reachable subordinate capability.

### 9. Minimum-Necessary Delegated Headers (EMPTY Header Set)
In Phase 4.1, backend MCP servers (`so-mcp`, `diag-mcp`) contain no inbound correlation, identity, or audit header consumers.
- No delegated/user/security headers are required on the Phase 4.1 second hop.
- The Phase 4.1 downstream second-hop custom header set is strictly **EMPTY**.
- `X-Correlation-ID` is **NOT relayed** in Phase 4.1. Trace-header relay may be added later if backend inbound correlation propagation is explicitly implemented.
- `Authorization` (raw external JWT), `X-User-ID`, `X-User-Role`, `X-Production-Write`, and `X-Attachment-Access` are **NOT relayed**.

### 10. Request-Scoped Ephemeral State
Each invocation of `investigate_incident` executes with a fresh, request-scoped `InMemoryInvestigationStore` and `InvestigationApplicationService` lifecycle. Durable multi-request persistence is out of scope and deferred to a future phase.

### 11. Architecture Boundaries
- `investigation_mcp` contains zero imports of `platform_gateway`.
- `platform_investigation_service` contains zero imports of the `mcp` SDK.
- Raw external Bearer JWTs terminate strictly at the Gateway.

### 12. D08 Compliance Separation
Phase 4 development and automated testing are permitted using synthetic datasets. Exposing confidential investigation payloads to external AI reasoning providers in production remains disabled pending formal DPIA / security compliance approval.

---

## Consequences

### Positive
- Preserves clear Layer-2 vs Layer-4 boundaries without turning Gateway into an orchestrator.
- Eliminates privilege amplification risk without duplicating RBAC logic in `investigation-mcp`.
- Maintains independent deployment, fault domains, and horizontal scalability.
- Enforces strict minimum-necessary header relaying.

### Negative / Operational Constraints
- Production second-hop traffic is blocked until infrastructure network policies are deployed.
- Composite tool is restricted to L3 users in the initial baseline; L2 users cannot access it until a separate capability profile is designed.

---

## Phase 4.2 Security Amendment — Low-Level MCP Public Boundary & SDK Baseline

### Context & Defect Identification
During Phase 4.2 public boundary security verification, an input-validation value-echo defect was identified in the high-level FastMCP tool registration path under `mcp==1.29.1`. FastMCP's pre-function argument validation (`call_fn_with_arg_validation`) catches Pydantic validation errors before tool function invocation and stringifies the exception into `ToolError(f"Error executing tool {self.name}: {e}")`. Pydantic's default string representation includes `input_value='...'`, causing raw caller-supplied values (including unexpected extra fields or sensitive free-text) to be echoed back to the caller in tool error text. Furthermore, enforcing strict rejection of extra arguments on FastMCP function-argument tools required mutating private SDK internals (`_tool_manager.get_tool().fn_metadata.arg_model`), and FastMCP 1.29.1 provides no supported hook to intercept or sanitize pre-function validation errors.

### Decision
The `investigation-mcp` public tool boundary replaces the high-level FastMCP tool registration with the official MCP Python SDK low-level `Server` boundary (`mcp.server.lowlevel.Server`):
1. **Official Low-Level MCP SDK**: Uses official `mcp.server.lowlevel.Server` with `@server.list_tools()` and `@server.call_tool(validate_input=False)`. It is NOT custom JSON-RPC; it remains standard official MCP SDK.
2. **Streamable HTTP Preservation**: Preserves ADR 007 stateless Streamable HTTP transport via official SDK `StreamableHTTPSessionManager` (`mcp.server.streamable_http_manager`).
3. **Application-Controlled Validation**: By setting `validate_input=False` at the low-level server registration, raw arguments are dispatched directly to the Investigation handler, which executes `InvestigateIncidentRequestDTO.model_validate(arguments)` and catches validation errors inside application code.
4. **Zero Caller-Input Echo**: Validation formatting uses `exc.errors(include_input=False, include_url=False)`, exposing only public field paths and generic constraint descriptions while guaranteeing zero echo of raw caller values, free-text hypotheses, or unexpected parameters.
5. **Direct Public Fields & Closed Schemas**: Advertises closed `inputSchema` (`additionalProperties: false`) directly from `InvestigateIncidentRequestDTO.model_json_schema(by_alias=True)` and closed `outputSchema` directly from `InvestigateIncidentResponseDTO.model_json_schema(by_alias=True)`. Eliminates all reliance on private `FastMCP._tool_manager` or `arg_model` metadata mutations.
6. **SDK Baseline Confirmation**: Authoritative MCP SDK dependency baseline is `mcp==1.29.1` (locked in `uv.lock`, declared as `mcp>=1.3.0,<2.0.0`). The prior `1.26.0` statement in walkthrough reporting was an errant transcription error; no SDK version change or lockfile modification occurred.
