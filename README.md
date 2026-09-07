# SuperOffice AI Support MCP Platform

A secure, modular MCP platform for AI-assisted SuperOffice L1/L2/L3 support and cross-system incident investigation.

## Status

Architecture and project foundation.

Implementation has not started.

## Architecture

The platform is designed around:

* MCP Gateway
* SuperOffice MCP
* Diagnostics MCP
* Knowledge MCP
* Infrastructure MCP
* Application Services
* Integration Clients
* Security and Policy Layer

## Security

The system follows:

* deny-by-default
* least privilege
* RBAC
* data minimization
* PII protection
* attachment protection
* secret protection
* audit logging

See:

* `docs/architecture.md`
* `docs/security-model.md`
* `docs/data-classification.md`

## Development

Development instructions and architectural constraints are maintained under:

`.agents/rules/`

Reusable development workflows are maintained under:

`.agents/workflows/`

## Project Documentation

See the `docs/` directory for architecture, requirements, investigation methodology and security documentation.
