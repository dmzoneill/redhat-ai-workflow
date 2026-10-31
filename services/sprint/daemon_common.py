"""Shared constants and helpers for the sprint bot daemon."""

import asyncio
import logging
from asyncio.subprocess import Process
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dbus_next.errors import DBusError

# Sprint daemon owns its own state file - no shared file with other services
from server.paths import SPRINT_STATE_FILE_V2
from services.base.dbus import DBUS_AVAILABLE, MessageBus

PROJECT_ROOT = Path(__file__).parent.parent.parent
SPRINT_STATE_FILE = SPRINT_STATE_FILE_V2

# Directory for background work logs
SPRINT_WORK_DIR = PROJECT_ROOT / "memory" / "state" / "sprint_work"

logger = logging.getLogger(__name__)

# Failures a daemon step or D-Bus handler reports instead of crashing the service:
# I/O and subprocess errors, bad payloads, D-Bus/RPC failures and timeouts.
RECOVERABLE_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    LookupError,
    AttributeError,
    asyncio.TimeoutError,
    yaml.YAMLError,
    DBusError,
)


def _local_now() -> datetime:
    """Current local wall-clock time as a naive datetime (the format persisted in sprint state)."""
    return datetime.now(timezone.utc).astimezone().replace(tzinfo=None)


def _log_safe(value: Any) -> str:
    """Return value as a single-line string so it cannot forge log entries."""
    return str(value).replace("\r", "").replace("\n", "")


# Maximum timeline entries per issue to prevent unbounded memory growth
MAX_TIMELINE_ENTRIES = 50


def _add_timeline_event(issue: dict, event: dict) -> None:
    """Add a timeline event to an issue, trimming old entries if needed."""
    if "timeline" not in issue:
        issue["timeline"] = []
    issue["timeline"].append(event)
    if len(issue["timeline"]) > MAX_TIMELINE_ENTRIES:
        issue["timeline"] = issue["timeline"][-MAX_TIMELINE_ENTRIES:]


async def spawn_claude_cli(claude_path: str, prompt: str) -> Process:
    """Start ``claude --print`` non-interactively in the project root with piped output."""
    return await asyncio.create_subprocess_exec(
        claude_path,
        "--print",
        "--dangerously-skip-permissions",
        prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(PROJECT_ROOT),
    )


async def connect_chat_interface() -> tuple[Any, Any]:
    """Connect to the VS Code extension's chat D-Bus service; returns ``(bus, chat_interface)``."""
    if not DBUS_AVAILABLE:
        raise RuntimeError("dbus-next is not installed")
    bus = await MessageBus().connect()
    introspection = await bus.introspect("com.aiworkflow.Chat", "/com/aiworkflow/Chat")
    proxy = bus.get_proxy_object("com.aiworkflow.Chat", "/com/aiworkflow/Chat", introspection)
    return bus, proxy.get_interface("com.aiworkflow.Chat")
