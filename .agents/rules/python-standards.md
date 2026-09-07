Use:

- Python 3.12+
- uv
- official MCP Python SDK v2
- FastMCP where appropriate
- Pydantic
- httpx
- pytest
- ruff
- mypy

Standards:

- type hints everywhere practical
- async I/O for network/database operations
- small cohesive modules
- dependency injection where appropriate
- explicit interfaces
- structured logging
- typed exceptions
- no secrets in source
- no hidden side effects
- tests for security-sensitive behavior