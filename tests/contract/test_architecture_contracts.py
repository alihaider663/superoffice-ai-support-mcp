"""Static cross-component architecture and dependency invariant contract tests."""

import ast
from pathlib import Path

# Locate the root of the source tree
SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "src"


def _get_imports_from_file(file_path: Path) -> list[str]:
    """Parse a Python file into an AST and extract all top-level and from imports."""
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except Exception:
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def _get_package_imports(package_dir: Path) -> dict[str, list[str]]:
    """Extract all imports from all Python files in a package directory."""
    package_imports: dict[str, list[str]] = {}
    for py_file in package_dir.rglob("*.py"):
        rel_path = str(py_file.relative_to(package_dir))
        package_imports[rel_path] = _get_imports_from_file(py_file)
    return package_imports


# ============================================================================
# 1. Server & Gateway Isolation Dependency Tests
# ============================================================================


def test_server_packages_do_not_import_each_other() -> None:
    """Verify MCP server packages maintain complete fault-domain isolation."""
    servers_dir = SRC_ROOT / "servers"

    so_imports = _get_package_imports(servers_dir / "superoffice" / "src" / "so_mcp")
    diag_imports = _get_package_imports(servers_dir / "diagnostics" / "src" / "diag_mcp")
    kb_imports = _get_package_imports(servers_dir / "knowledge" / "src" / "kb_mcp")

    # SuperOffice must not import other servers
    for file_path, imports in so_imports.items():
        for imp in imports:
            assert not any(imp.startswith(s) for s in ("diag_mcp", "kb_mcp", "infra_mcp")), (
                f"SuperOffice file {file_path} illegally imports {imp}"
            )

    # Diagnostics must not import other servers
    for file_path, imports in diag_imports.items():
        for imp in imports:
            assert not any(imp.startswith(s) for s in ("so_mcp", "kb_mcp", "infra_mcp")), (
                f"Diagnostics file {file_path} illegally imports {imp}"
            )

    # Knowledge must not import other servers
    for file_path, imports in kb_imports.items():
        for imp in imports:
            assert not any(imp.startswith(s) for s in ("so_mcp", "diag_mcp", "infra_mcp")), (
                f"Knowledge file {file_path} illegally imports {imp}"
            )


def test_gateway_does_not_import_server_domain_packages() -> None:
    """Verify MCP Gateway operates purely protocol-neutral without server domain packages."""
    gateway_dir = SRC_ROOT / "gateway" / "src" / "platform_gateway"
    gateway_imports = _get_package_imports(gateway_dir)

    server_namespaces = ("so_mcp", "diag_mcp", "kb_mcp", "infra_mcp")
    for file_path, imports in gateway_imports.items():
        for imp in imports:
            assert not any(imp.startswith(s) for s in server_namespaces), (
                f"Gateway file {file_path} illegally imports server package {imp}"
            )


def test_production_code_does_not_import_test_packages() -> None:
    """Verify production code under src/ never imports from tests or test fakes."""
    src_imports = _get_package_imports(SRC_ROOT)

    test_namespaces = ("tests", "tests.fakes", "pytest")
    for file_path, imports in src_imports.items():
        for imp in imports:
            assert not any(imp.startswith(t) for t in test_namespaces), (
                f"Production file {file_path} illegally imports test package {imp}"
            )


def test_platform_core_is_foundational() -> None:
    """Verify platform-core has no dependencies on servers, gateway, or other shared packages."""
    core_dir = SRC_ROOT / "shared" / "platform-core" / "src" / "platform_core"
    core_imports = _get_package_imports(core_dir)

    higher_namespaces = (
        "so_mcp",
        "diag_mcp",
        "kb_mcp",
        "infra_mcp",
        "platform_gateway",
        "platform_config",
        "platform_observability",
        "platform_security",
        "platform_http",
        "platform_investigation",
    )
    for file_path, imports in core_imports.items():
        for imp in imports:
            assert not any(imp.startswith(h) for h in higher_namespaces), (
                f"platform_core file {file_path} illegally imports higher-level package {imp}"
            )
