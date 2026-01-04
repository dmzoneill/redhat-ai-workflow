"""Pytest configuration and shared fixtures."""

import os
import sys
from pathlib import Path

import pytest

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture
def config_path(project_root):
    """Return path to config.json."""
    return project_root / "config.json"


@pytest.fixture
def skills_dir(project_root):
    """Return path to skills directory."""
    return project_root / "skills"


@pytest.fixture
def personas_dir(project_root):
    """Return path to agents directory."""
    return project_root / "personas"


@pytest.fixture
def temp_dir(tmp_path):
    """Return a temporary directory for test files."""
    return tmp_path


@pytest.fixture(autouse=True)
def setup_env():
    """Set up environment variables for testing."""
    # Save original values
    original_env = dict(os.environ)

    # Set test environment
    os.environ.setdefault("TESTING", "1")

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)
