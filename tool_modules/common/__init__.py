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


# ==================== Google Services Shared Config ====================
#
# All Google tool modules (calendar, gmail, gdrive, slides) share the same
# OAuth token and config directory. These helpers centralise the config
# so it is defined in exactly one place.

# Default scopes -- used when config.json has no google.oauth_scopes entry.
_DEFAULT_GOOGLE_OAUTH_SCOPES: list[str] = [
    # Calendar
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    # Gmail
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    # Slides
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/presentations.readonly",
    # Drive
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_google_oauth_scopes() -> list[str]:
    """Return the shared Google OAuth scopes list.

    Reads from config.json ``google.oauth_scopes`` with the built-in
    default list as fallback.
    """
    from server.utils import load_config

    config = load_config()
    return config.get("google", {}).get("oauth_scopes", _DEFAULT_GOOGLE_OAUTH_SCOPES)


def get_google_config_dir() -> Path:
    """Return the shared Google config directory as a Path.

    Resolution order (first match wins):
      1. config.json  ``google.config_dir``
      2. config.json  ``google_calendar.config_dir``
      3. config.json  ``paths.google_calendar_config``
      4. ``~/.config/google-calendar``  (hardcoded fallback)
    """
    import os

    from server.utils import load_config

    config = load_config()

    # 1. google.config_dir  (new canonical location)
    val = config.get("google", {}).get("config_dir")
    if val:
        return Path(os.path.expanduser(val))

    # 2. google_calendar.config_dir  (legacy)
    val = config.get("google_calendar", {}).get("config_dir")
    if val:
        return Path(os.path.expanduser(val))

    # 3. paths.google_calendar_config  (legacy)
    val = config.get("paths", {}).get("google_calendar_config")
    if val:
        return Path(os.path.expanduser(val))

    # 4. Hardcoded default
    return Path.home() / ".config" / "google-calendar"


def get_google_calendar_settings() -> dict:
    """Return calendar-specific settings from config.json.

    Returns a dict with keys:
        timezone (str)           -- default ``"Europe/Dublin"``
        meeting_start_hour (int) -- default ``15``
        meeting_end_hour (int)   -- default ``19``
    """
    from server.utils import load_config

    config = load_config()
    gc = config.get("google_calendar", {})
    window = gc.get("meeting_window", {})

    return {
        "timezone": gc.get("timezone", "Europe/Dublin"),
        "meeting_start_hour": window.get("start_hour", 15),
        "meeting_end_hour": window.get("end_hour", 19),
    }


def get_meet_bot_timezone() -> str:
    """Return the timezone for the meet bot / meeting scheduler.

    Resolution order:
      1. config.json  ``meet_bot.timezone``
      2. config.json  ``schedules.timezone``
      3. config.json  ``google_calendar.timezone``
      4. ``"Europe/Dublin"``
    """
    from server.utils import load_config

    config = load_config()

    val = config.get("meet_bot", {}).get("timezone")
    if val:
        return val

    val = config.get("schedules", {}).get("timezone")
    if val:
        return val

    val = config.get("google_calendar", {}).get("timezone")
    if val:
        return val

    return "Europe/Dublin"
