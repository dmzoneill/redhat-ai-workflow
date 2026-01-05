"""Common utilities for tool modules.

This module provides shared infrastructure for all tool modules,
reducing boilerplate and ensuring consistency.

Usage in tool modules:
    from tool_modules.common import PROJECT_ROOT, setup_path
    setup_path()  # Adds project root to sys.path

    # Now can import from server
    from server.utils import run_cmd, truncate_output
"""

import sys
from pathlib import Path

# Compute project root once at import time
# This file is at: tool_modules/common/__init__.py
# Project root is 2 levels up: redhat-ai-workflow/
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Also export as string for convenience
PROJECT_ROOT_STR = str(PROJECT_ROOT)


def setup_path() -> None:
    """Add project root to sys.path if not already present.

    This allows tool modules to import from the server package.
    Should be called at the top of each tool module.
    """
    if PROJECT_ROOT_STR not in sys.path:
        sys.path.insert(0, PROJECT_ROOT_STR)


def get_project_root() -> Path:
    """Get the project root directory."""
    return PROJECT_ROOT


# Auto-setup path on import for convenience
# This way, tool modules can just do: from tool_modules.common import PROJECT_ROOT
setup_path()
