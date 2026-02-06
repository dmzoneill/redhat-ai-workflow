"""
Centralized path configuration for scripts.

This module provides a single source of truth for project paths and sys.path setup.
Import from here instead of calculating PROJECT_ROOT in each script.

Usage:
    from scripts.common.paths import PROJECT_ROOT, setup_path
    setup_path()  # Adds project root to sys.path

    # Now can import from server, services, etc.
    from server.utils import load_config
"""

import sys
from pathlib import Path

# Project root is 2 levels up from this file (scripts/common/paths.py)
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()

# Common directories
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SERVER_DIR = PROJECT_ROOT / "server"
SERVICES_DIR = PROJECT_ROOT / "services"
TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"
MEMORY_DIR = PROJECT_ROOT / "memory"
SKILLS_DIR = PROJECT_ROOT / "skills"
PERSONAS_DIR = PROJECT_ROOT / "personas"
CONFIG_DIR = Path.home() / ".config" / "aa-workflow"


def setup_path() -> None:
    """Add project root to sys.path if not already present.

    This allows scripts to import from the server package and other
    project modules without needing to install them.

    Should be called at the top of each script that needs to import
    from project modules.
    """
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


def get_config_file() -> Path:
    """Get the path to config.json."""
    return CONFIG_DIR / "config.json"


def get_state_file() -> Path:
    """Get the path to state.json."""
    return CONFIG_DIR / "state.json"


# Auto-setup path on import for convenience
setup_path()
