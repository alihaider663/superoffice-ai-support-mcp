## Description

<!-- Provide a concise description of the changes introduced by this pull request. -->

## Type of Change

- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature (non-breaking change adding functionality)
- [ ] Refactoring / Code quality improvement
- [ ] Documentation update
- [ ] CI / Tooling configuration

## Architecture & Security Checklist

- [ ] **Six-Layer Architecture**: Preserves service layer boundaries; no direct AI access to databases or backend infrastructure.
- [ ] **Deny-by-Default RBAC**: Tool permissions and role mappings defined and enforced.
- [ ] **No Secrets or Credentials**: Zero API keys, passwords, tokens, or private keys committed.
- [ ] **No Real Customer Data / PII**: All fixtures use synthetic mock data.
- [ ] **Database Invariants**: Adheres to 5s statement timeout (D01), 50-row limit (D02), and `SNAPSHOT` isolation (D09); zero arbitrary SQL.
- [ ] **Attachment Protection (D05)**: Metadata only; zero raw file downloads to external AI models.
- [ ] **Data Minimization (D08)**: No confidential CRM data exported to external AI endpoints.

## Quality & Verification Gates

- [ ] `uv run pytest` passes cleanly (100% passing tests).
- [ ] `uv run ruff check src tests` reports zero linting errors.
- [ ] `uv run ruff format --check src tests` reports all files formatted.
- [ ] `uv run mypy src tests` reports zero type errors.
- [ ] Documentation updated where relevant (`docs/`, `README.md`).
