"""Module execution entrypoint for Knowledge Ingestion CLI."""

import sys

from kb_mcp.ingestion.cli import main

if __name__ == "__main__":
    sys.exit(main())
