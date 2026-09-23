"""SuperOffice MCP Server STDIO runtime application entrypoint."""

from so_mcp.server import create_superoffice_mcp_server


def main() -> None:
    """Run SuperOffice MCP server over STDIO for direct client integration."""
    server = create_superoffice_mcp_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
