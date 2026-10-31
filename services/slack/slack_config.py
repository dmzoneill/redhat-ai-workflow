"""Slack daemon configuration and credential refresh.

Settings come from the ``slack`` section of config.json; environment variables
override individual keys. Importing this module also puts
``tool_modules/aa_slack`` on ``sys.path`` (for the ``src.*`` Slack client
modules) and loads the Slack ``.env`` files, as the daemon always did.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from scripts.common.config_loader import load_config

PROJECT_ROOT = Path(os.path.abspath(__file__)).parents[2]

sys.path.insert(0, os.path.join(str(PROJECT_ROOT), "tool_modules", "aa_slack"))

load_dotenv(PROJECT_ROOT / "tool_modules" / "aa_slack" / ".env")
load_dotenv()


class SlackSettings:
    """The loaded config.json, reloadable after a credential refresh."""

    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.slack: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        """Re-read config.json."""
        self.config = load_config()
        self.slack = self.config.get("slack", {})

    def get(self, key: str, default: Any = None, env_var: str | None = None) -> Any:
        """Return a dotted ``key`` from the slack section; ``env_var`` wins when set."""
        if env_var and os.getenv(env_var):
            return os.getenv(env_var)
        value: Any = self.slack
        for part in key.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        return value if value is not None else default


SETTINGS = SlackSettings()


def __getattr__(name: str) -> Any:
    """Keep ``CONFIG`` and ``SLACK_CONFIG`` pointing at the current settings."""
    if name == "CONFIG":
        return SETTINGS.config
    if name == "SLACK_CONFIG":
        return SETTINGS.slack
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_slack_config(key: str, default: Any = None, env_var: str | None = None) -> Any:
    """
    Get a Slack config value with environment variable override.

    Priority: Environment variable > config.json > default
    """
    return SETTINGS.get(key, default, env_var)


def refresh_slack_credentials() -> bool:
    """
    Run get_slack_creds.py to refresh credentials from Chrome.

    Returns True if successful, False otherwise.
    """
    script_path = PROJECT_ROOT / "scripts" / "get_slack_creds.py"
    if not script_path.exists():
        print(f"⚠️  Credential refresh script not found: {script_path}")
        return False

    print("🔄 Attempting to refresh Slack credentials from Chrome...")
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("⚠️  Credential refresh timed out")
        return False
    except OSError as e:
        print(f"⚠️  Credential refresh error: {e}")
        return False

    if result.returncode != 0:
        print(f"⚠️  Credential refresh failed: {result.stderr or result.stdout}")
        return False

    print("✅ Credentials refreshed from Chrome")
    SETTINGS.reload()
    return True
