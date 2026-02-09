"""Workspace State Exporter - Export unified UI state for VS Code extension.

Exports ALL UI data to a single JSON file that the VS Code extension watches
for real-time updates. This is the single source of truth for the Command Center.

The exported file is written to:
  ~/.config/aa-workflow/workspace_states.json

The VS Code extension uses a file watcher to detect changes and update
ALL UI sections accordingly (no manual refresh buttons needed).

Export format (v3):
{
    "version": 3,
    "exported_at": "2024-01-18T12:00:00",

    // Session data
    "workspace_count": 1,
    "session_count": 2,
    "workspaces": { ... },
    "sessions": [ ... ],

    // Service status
    "services": {
        "slack": {"running": true, "uptime": "3.0d", ...},
        "cron": {"running": true, "uptime": "1.9h", "jobs": 5, ...},
        "meet": {"running": false},
        "mcp": {"running": true, "pid": 12345}
    },

    // Ollama instances
    "ollama": {
        "npu": {"available": true, "port": 11434, "model": "qwen2.5:0.5b"},
        "igpu": {"available": false, "port": 11435, ...},
        ...
    },

    // Cron configuration and history
    "cron": {
        "enabled": true,
        "timezone": "UTC",
        "execution_mode": "claude_cli",
        "jobs": [...],
        "history": [...],
        "total_history": 42
    },

    // Slack channels
    "slack_channels": ["general", "random", ...],

    // Sprint issues (cached)
    "sprint_issues": [...],
    "sprint_issues_updated": "2024-01-18T12:00:00"
}
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from fastmcp import Context

from server.paths import AA_CONFIG_DIR, WORKSPACE_STATES_FILE

logger = logging.getLogger(__name__)

# Export file location - centralized in server.paths
EXPORT_DIR = AA_CONFIG_DIR
EXPORT_FILE = WORKSPACE_STATES_FILE


def _ensure_export_dir() -> None:
    """Ensure the export directory exists."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def export_workspace_state(
    cleanup_stale: bool = False, max_stale_hours: int = 24
) -> dict:
    """Export workspace states to JSON file (legacy v2 format).

    For full unified export with all UI data, use export_workspace_state_with_data().

    This function preserves existing sprint/cron/service data from the file
    to prevent accidental data loss when called without those parameters.

    Args:
        cleanup_stale: If True, remove stale workspaces before export.
        max_stale_hours: Hours of inactivity before a workspace is considered stale

    Returns:
        Dictionary with export status and workspace count.
    """
    # Load existing data to preserve sprint/cron/service data
    existing_data = {}
    if EXPORT_FILE.exists():
        try:
            with open(EXPORT_FILE, encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception as exc:
            logger.debug("Suppressed error: %s", exc)

    # Delegate to unified export, preserving existing data
    return export_workspace_state_with_data(
        cleanup_stale=cleanup_stale,
        max_stale_hours=max_stale_hours,
        # Preserve existing data from legacy file
        services=existing_data.get("services"),
        ollama=existing_data.get("ollama"),
        cron=existing_data.get("cron"),
        slack_channels=existing_data.get("slack_channels"),
        sprint_issues=existing_data.get("sprint_issues"),
        sprint_issues_updated=existing_data.get("sprint_issues_updated"),
        meet=existing_data.get("meet"),
        sprint=existing_data.get("sprint"),
        sprint_history=existing_data.get("sprint_history"),
        performance=existing_data.get("performance"),
    )


def export_workspace_state_with_data(
    cleanup_stale: bool = False,
    max_stale_hours: int = 24,
    services: dict | None = None,
    ollama: dict | None = None,
    cron: dict | None = None,
    slack_channels: list | None = None,
    sprint_issues: list | None = None,
    sprint_issues_updated: str | None = None,
    meet: dict | None = None,
    sprint: dict | None = None,
    sprint_history: list | None = None,
    performance: dict | None = None,
) -> dict:
    """Export unified UI state to JSON file.

    DEPRECATED: Each service now writes its own state file.
    This function is kept for backward compatibility.

    Args:
        cleanup_stale: If True, remove stale workspaces before export.
        max_stale_hours: Hours of inactivity before a workspace is considered stale
        services: Service status dict (slack, cron, meet, mcp)
        ollama: Ollama instance status dict
        cron: Cron config and history dict
        slack_channels: List of Slack channel names
        sprint_issues: List of sprint issues (legacy, use sprint instead)
        sprint_issues_updated: ISO timestamp of when sprint issues were last fetched
        meet: Meet bot data (upcoming meetings, countdown, calendars)
        sprint: Full sprint state (currentSprint, issues, botEnabled, etc.)
        sprint_history: List of completed sprints
        performance: Performance tracking data (quarterly connection)

    Returns:
        Dictionary with export status.
    """
    from server.workspace_state import WorkspaceRegistry

    _ensure_export_dir()

    # Full sync with Cursor's database before export
    sync_result = WorkspaceRegistry.sync_all_with_cursor()
    if sum(sync_result.values()) > 0:
        logger.info(
            "Synced with Cursor DB before export: "
            f"+{sync_result['added']} -{sync_result['removed']} ~{sync_result['renamed']}"
        )

    # Clean up stale workspaces before export (disabled by default)
    cleaned_count = 0
    if cleanup_stale:
        cleaned_count = WorkspaceRegistry.cleanup_stale(max_stale_hours)

    # Get all workspace states
    all_states = WorkspaceRegistry.get_all_as_dict()

    # Get flattened sessions list for easier UI consumption
    all_sessions = WorkspaceRegistry.get_all_sessions()

    # Load existing data to preserve keys not managed by sync (e.g., performance)
    existing_data = {}
    if EXPORT_FILE.exists():
        try:
            with open(EXPORT_FILE, encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception as exc:
            logger.debug("Suppressed error: %s", exc)

    # SAFETY: If registry is empty but file has workspaces, preserve them
    # This prevents data loss when called from standalone scripts where
    # WorkspaceRegistry isn't populated
    if not all_states and existing_data.get("workspaces"):
        logger.warning(
            f"WorkspaceRegistry empty but file has {len(existing_data['workspaces'])} workspaces. "
            "Preserving existing workspaces."
        )
        all_states = existing_data["workspaces"]
        all_sessions = existing_data.get("sessions", [])

    # Build export data (v3 format with all UI data)
    export_data = {
        "version": 3,
        "exported_at": datetime.now().isoformat(),
        # Session data
        "workspace_count": len(all_states),
        "session_count": (
            len(all_sessions)
            if all_sessions
            else sum(len(ws.get("sessions", {})) for ws in all_states.values())
        ),
        "workspaces": all_states,
        "sessions": all_sessions,
        # Service status
        "services": services or {},
        # Ollama instances
        "ollama": ollama or {},
        # Cron configuration and history
        "cron": cron or {},
        # Slack channels
        "slack_channels": slack_channels or [],
        # Sprint issues (legacy - kept for backward compatibility)
        "sprint_issues": sprint_issues or [],
        "sprint_issues_updated": sprint_issues_updated or "",
        # Full sprint state (new format for Sprint Bot Autopilot)
        "sprint": sprint
        or {
            "currentSprint": None,
            "issues": [],
            "botEnabled": False,
            "lastUpdated": datetime.now().isoformat(),
            "processingIssue": None,
        },
        "sprint_history": sprint_history or [],
        # Meet bot data (upcoming meetings, countdown, calendars)
        "meet": meet or {},
        # Performance tracking data (quarterly connection)
        "performance": performance or existing_data.get("performance", {}),
    }

    # Write to file atomically (write to temp, then rename)
    # This prevents race conditions between sync script and MCP server
    try:
        import os
        import tempfile

        # Write to temp file in same directory (ensures same filesystem for atomic rename)
        temp_fd, temp_path = tempfile.mkstemp(
            suffix=".tmp", prefix="workspace_states_", dir=EXPORT_DIR
        )
        try:
            with os.fdopen(temp_fd, "w") as f:
                json.dump(export_data, f, indent=2, default=str)
            # Atomic rename (on POSIX systems)
            os.replace(temp_path, EXPORT_FILE)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except OSError as exc:
                logger.debug("OS operation failed: %s", exc)
            raise

        logger.debug(
            f"Exported v3: {len(all_states)} workspace(s), {len(all_sessions)} session(s), "
            f"{len(services or {})} services, {len(ollama or {})} ollama instances"
        )
        return {
            "success": True,
            "workspace_count": len(all_states),
            "session_count": len(all_sessions),
            "cleaned_count": cleaned_count,
            "file": str(EXPORT_FILE),
        }
    except Exception as e:
        logger.error(f"Failed to export workspace state: {e}")
        return {"success": False, "error": str(e)}


async def export_workspace_state_async(ctx: "Context" = None) -> dict:
    """Export workspace state asynchronously.

    If ctx is provided, ensures the current workspace is included
    in the export.

    Args:
        ctx: Optional MCP Context to ensure current workspace is included

    Returns:
        Dictionary with export status.
    """
    from server.workspace_state import WorkspaceRegistry

    logger.info(f"export_workspace_state_async called with ctx={ctx is not None}")

    # Ensure current workspace is registered if ctx provided
    if ctx:
        state = await WorkspaceRegistry.get_for_ctx(ctx)
        logger.info(
            f"Registered workspace: {state.workspace_uri}, project={state.project}"
        )

    # Log current registry state before export
    all_workspaces = WorkspaceRegistry.get_all_as_dict()
    logger.info(
        f"WorkspaceRegistry has {len(all_workspaces)} workspace(s) before export"
    )

    result = export_workspace_state()
    logger.info(f"Export result: {result}")
    return result


def get_export_file_path() -> Path:
    """Get the path to the export file.

    Returns:
        Path to workspace_state.json
    """
    return EXPORT_FILE


def read_exported_state() -> dict | None:
    """Read the exported workspace state.

    Useful for debugging or testing.

    Returns:
        Exported state dict or None if file doesn't exist.
    """
    if not EXPORT_FILE.exists():
        return None

    try:
        with open(EXPORT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read exported state: {e}")
        return None


def clear_exported_state() -> bool:
    """Clear the exported state file.

    Returns:
        True if cleared, False otherwise.
    """
    try:
        if EXPORT_FILE.exists():
            EXPORT_FILE.unlink()
        return True
    except Exception as e:
        logger.error(f"Failed to clear exported state: {e}")
        return False


# Hook to export state when workspace changes
def _on_workspace_change() -> None:
    """Called when workspace state changes.

    This can be hooked into WorkspaceRegistry to auto-export on changes.
    """
    export_workspace_state()
