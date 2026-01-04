"""Entry point for running the MCP server.

Usage:
    python -m server                     # Run with default tools
    python -m server --agent developer   # Load developer persona
    python -m server --agent devops      # Load devops persona
    python -m server --tools git,jira    # Load specific tool modules
    python -m server --all               # Load all tools (may exceed limits)
"""

from .main import main

if __name__ == "__main__":
    main()
