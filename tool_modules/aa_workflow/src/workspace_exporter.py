"""Workspace State Exporter - Export workspace state for VS Code extension.

Exports workspace state to a JSON file that the VS Code extension can watch
for real-time updates about active workspaces, sessions, personas, and tools.

The exported file is written to:
  ~/.mcp/workspace_states/workspace_states.json

The VS Code extension uses a file watcher to detect changes and update
the UI accordingly.

Export format (v2):
{
    "version": 2,
    "exported_at": "2024-01-18T12:00:00",
    "workspace_count": 1,
    "session_count": 2,
    "workspaces": {
        "file:///path/to/workspace": {
            "workspace_uri": "...",
            "project": "my-project",
            "sessions": {
                "abc123": { session details },
                "def456": { session details }
            },
            "active_session_id": "abc123"
        }
    },
    "sessions": [
        { flattened session with workspace info }
    ]
}
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

logger = logging.getLogger(__name__)

# Export file location - must match VS Code extension's expected path
EXPORT_DIR = Path.home() / ".mcp" / "workspace_states"
EXPORT_FILE = EXPORT_DIR / "workspace_states.json"


def _ensure_export_dir() -> None:
    """Ensure the export directory exists."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def export_workspace_state(cleanup_stale: bool = False, max_stale_hours: int = 24) -> dict:
    """Export all workspace states to JSON file.

    This function is called periodically or when workspace state changes.
    The VS Code extension watches this file for updates.

    Args:
        cleanup_stale: If True, remove stale workspaces before export.
                       Default is False to preserve sessions across exports.
        max_stale_hours: Hours of inactivity before a workspace is considered stale

    Returns:
        Dictionary with export status and workspace count.
    """
    from server.workspace_state import WorkspaceRegistry

    _ensure_export_dir()

    # Sync session names from Cursor's database before export
    # This ensures the UI shows the correct chat names
    synced_count = WorkspaceRegistry.sync_all_session_names()
    if synced_count > 0:
        logger.info(f"Synced {synced_count} session name(s) from Cursor DB before export")

    # Clean up stale workspaces before export (disabled by default to preserve sessions)
    cleaned_count = 0
    if cleanup_stale:
        cleaned_count = WorkspaceRegistry.cleanup_stale(max_stale_hours)

    # Get all workspace states
    all_states = WorkspaceRegistry.get_all_as_dict()

    # Get flattened sessions list for easier UI consumption
    all_sessions = WorkspaceRegistry.get_all_sessions()

    # Build export data (v2 format with sessions)
    export_data = {
        "version": 2,
        "exported_at": datetime.now().isoformat(),
        "workspace_count": len(all_states),
        "session_count": WorkspaceRegistry.total_session_count(),
        "workspaces": all_states,
        "sessions": all_sessions,  # Flattened list of all sessions
    }

    # Write to file
    try:
        with open(EXPORT_FILE, "w") as f:
            json.dump(export_data, f, indent=2, default=str)
        logger.debug(f"Exported {len(all_states)} workspace(s), {len(all_sessions)} session(s) to {EXPORT_FILE}")
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
        logger.info(f"Registered workspace: {state.workspace_uri}, project={state.project}")

    # Log current registry state before export
    all_workspaces = WorkspaceRegistry.get_all_as_dict()
    logger.info(f"WorkspaceRegistry has {len(all_workspaces)} workspace(s) before export")

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
        with open(EXPORT_FILE) as f:
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
