# Contributing to SuperOffice AI Support MCP Platform

Thank you for contributing to the SuperOffice AI Support MCP Platform. This guide outlines development practices, quality gates, and security requirements for all contributors.

---

## Prerequisites

- **Python**: `>= 3.12`
- **uv**: Modern, fast Python package and project manager ([docs](https://docs.astral.sh/uv/))
- **Git**: `>= 2.40`
- **Optional Local Services**:
  - PostgreSQL `>= 16` with `pgvector` extension (for local Knowledge database testing)
  - Microsoft SQL Server (for optional live Diagnostics MCP testing)

---

## Local Development Workflow

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd superoffice-ai-support-mcp
   ```

2. **Set up virtual environment & dependencies**:
   ```bash
   uv sync
   ```

3. **Configure local environment**:
   Copy `.env.example` to `.env` and fill in local development placeholders:
   ```bash
   cp .env.example .env
   ```

4. **Run pre-flight check**:
   ```powershell
   powershell -File scripts/check-local.ps1
   ```

---

## Quality Gates & Verification

Before submitting any pull/merge request, your changes must pass the entire local verification suite with zero errors or warnings:

1. **Test Suite**:
   ```bash
   uv run pytest
   ```
   *All 1043+ regression tests must pass. Live integration tests requiring real upstream databases are opt-in and will be skipped automatically when services are not configured.*

2. **Linting & Code Style**:
   ```bash
   uv run ruff check src tests
   uv run ruff format --check src tests
   ```

3. **Strict Type Checking**:
   ```bash
   uv run mypy src tests
   ```

To auto-format code according to project style rules:
```bash
uv run ruff format src tests
uv run ruff check --fix src tests
```

---

## Security & Architecture Constraints

Contributors must adhere strictly to the platform's core architecture and security policies:

1. **Zero Secret / Credential Commits**:
   - Never commit passwords, tokens, API keys, private keys, or `.env` files.
   - All tests must use synthetic mock credentials or test fixture helpers.

2. **Zero Live Customer / CRM Data**:
   - Never commit real customer names, phone numbers, email addresses, or ticket descriptions.
   - Use synthetic fixture data (`tests/fixtures/`) for unit and contract testing.

3. **Zero Arbitrary SQL / Shell Execution**:
   - All database access in Diagnostics MCP must use strictly bounded, pre-vetted stored procedures or parameterized DMV queries under `SNAPSHOT` isolation.
   - Arbitrary dynamic SQL (`EXEC(...)`), `WITH (NOLOCK)` hints, and shell command execution tools are strictly prohibited.

4. **Attachment Content Protection (Decision D05)**:
   - Tool responses must never expose raw attachment downloads or automatic ingestion into LLM context.
   - Only attachment metadata is permitted.

5. **Layer Boundaries**:
   - Preserve the Six-Layer Architecture. External AI reasoning engines must never communicate directly with databases or backend integration clients; all traffic flows through the MCP Gateway.

---

## Commit & Pull / Merge Request Guidelines

1. **Branch Naming**:
   Use descriptive prefixes: `feat/<name>`, `fix/<name>`, `docs/<name>`, `refactor/<name>`, `test/<name>`.

2. **Commit Messages**:
   Follow Conventional Commits format:
   - `feat: add <feature>`
   - `fix: resolve <bug>`
   - `docs: update <documentation>`
   - `test: add test coverage for <module>`
   - `chore: <maintenance task>`

3. **Pull / Merge Request Process**:
   - Ensure the description clearly outlines the problem solved, changes made, and verification steps.
   - Confirm all quality commands (`pytest`, `ruff check`, `ruff format --check`, `mypy`) pass cleanly.
   - Update relevant documentation in `docs/` and `README.md` if public tools, schemas, or behaviors change.
