This project handles potentially confidential SuperOffice data.

Security is deny-by-default.

Never assume that because the MCP server can access data, the AI agent should receive that data.

Data must be minimized before it reaches the model.

Attachments are deny-by-default.

Customer PII must be minimized or redacted where possible.

Secrets must never be returned to the model.

Never commit:

- passwords
- API keys
- OAuth secrets
- private keys
- connection strings
- production .env files
- customer exports
- production database dumps
- real customer attachments

Never provide unrestricted SQL execution.

Never provide unrestricted shell execution.

Production writes require explicit authorization and deterministic policy enforcement.

Do not rely on the LLM to enforce security.

Use authentication, RBAC, tool permissions, data classification, DLP and audit logging.