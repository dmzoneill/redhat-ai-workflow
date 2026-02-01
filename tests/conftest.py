"""Pytest configuration and shared fixtures."""

import asyncio
import os
import subprocess
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


# ============================================================================
# MeetBot Device Testing Fixtures
# ============================================================================


def _check_pulseaudio() -> bool:
    """Check if PulseAudio/PipeWire is available."""
    try:
        result = subprocess.run(["pactl", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def _check_pw_metadata() -> bool:
    """Check if pw-metadata is available."""
    try:
        result = subprocess.run(["which", "pw-metadata"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


# Skip markers
requires_pulseaudio = pytest.mark.skipif(not _check_pulseaudio(), reason="PulseAudio/PipeWire not available")

requires_pw_metadata = pytest.mark.skipif(not _check_pw_metadata(), reason="pw-metadata not available")


@pytest.fixture
def pulseaudio_available():
    """Check if PulseAudio is available for testing."""
    return _check_pulseaudio()


@pytest.fixture
async def saved_default_source():
    """Save and restore the default PulseAudio source around a test."""
    if not _check_pulseaudio():
        yield None
        return

    # Get current default
    proc = await asyncio.create_subprocess_exec(
        "pactl",
        "get-default-source",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    original = stdout.decode().strip() if proc.returncode == 0 else None

    yield original

    # Restore original
    if original:
        await asyncio.create_subprocess_exec(
            "pactl",
            "set-default-source",
            original,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )


@pytest.fixture
async def cleanup_meetbot_devices():
    """Fixture that cleans up meetbot devices after test."""
    yield

    if not _check_pulseaudio():
        return

    # Find and remove meetbot modules
    proc = await asyncio.create_subprocess_exec(
        "pactl",
        "list",
        "modules",
        "short",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()

    if proc.returncode == 0:
        for line in stdout.decode().split("\n"):
            if "meet_bot" in line.lower():
                parts = line.split("\t")
                if parts:
                    module_id = parts[0]
                    await asyncio.create_subprocess_exec(
                        "pactl",
                        "unload-module",
                        module_id,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
