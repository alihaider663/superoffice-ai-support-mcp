# ADR 005 — Model Provider Independence

## Status

Accepted

## Context

The platform provides MCP tools to an AI support agent. The AI model provider landscape is evolving rapidly — organizations may need to switch between providers (OpenAI, Anthropic, Google, self-hosted models) due to:

- Cost optimization
- Capability improvements
- Data residency requirements
- Organizational policy changes
- Vendor availability or reliability
- Privacy or regulatory requirements (e.g., requiring a self-hosted model to prevent customer data from leaving the organization)

If MCP tools are coupled to a specific AI provider's SDK, prompt format, or API conventions, switching providers requires modifying the entire MCP layer.

The project documentation explicitly states: "The architecture must remain independent of any particular AI model provider."

## Decision

The platform must not couple to any specific AI model provider.

### Rules

- MCP servers expose capabilities through the standard MCP protocol. They do not import or reference AI provider SDKs.
- MCP tool descriptions must be clear, self-documenting, and provider-neutral — they must work with any MCP-compatible client regardless of the underlying model.
- Application Services and Integration Clients must not contain AI-provider-specific logic.
- Data filtering, PII redaction, and security controls are implemented in the platform, not delegated to the AI provider.
- The AI agent (which calls MCP tools) is the only component that interfaces with a model provider. This component is outside the MCP platform boundary.

### Boundary

```text
┌─────────────────────────┐
│   AI Provider SDK       │  ← Provider-specific (outside MCP platform)
│   AI Agent              │
├─────────────────────────┤
│   MCP Protocol          │  ← Standard interface boundary
├─────────────────────────┤
│   MCP Gateway           │
│   MCP Servers           │  ← Provider-independent (this platform)
│   Application Services  │
│   Integration Clients   │
└─────────────────────────┘
```

## Alternatives Considered

### Tight Integration with a Single AI Provider

Rejected. Creates vendor lock-in. The AI provider landscape is volatile. Tight coupling would require re-engineering the MCP layer for every provider change.

### Multi-Provider Adapter Layer Inside MCP

Rejected. Unnecessary complexity. MCP is already a provider-independent protocol. Adding a provider abstraction layer inside the MCP platform would duplicate what the AI agent client already handles.

### Provider-Specific Prompt Templates in MCP Tools

Rejected. Tool descriptions must be universal. Provider-specific prompt engineering belongs in the AI agent configuration, not in MCP tool definitions.

## Consequences

### Positive

- The platform can be used with any MCP-compatible AI agent.
- Switching AI providers does not require changes to MCP servers, services, or integrations.
- Data residency requirements can be met by choosing an appropriate AI provider/deployment without modifying the platform.
- Tool descriptions and capabilities are universally comprehensible.

### Negative

- The platform cannot leverage provider-specific features (e.g., native tool-calling optimizations unique to one provider).
- Tool descriptions must be carefully written to be universally clear, which may require more effort than provider-optimized descriptions.
- The AI agent client (outside this platform) bears the responsibility of provider-specific configuration.

### Risks

- The security model documents that data sent to an external AI provider must be treated as leaving the protected boundary. If organizational policy prohibits this, a self-hosted or enterprise model deployment is required — this is an operational decision, not a platform change, but must be planned for.
- MCP protocol evolution could introduce provider-favoring extensions. The platform should track MCP specification changes and evaluate neutrality impact.
