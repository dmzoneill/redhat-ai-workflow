"""Workspace State - Per-workspace and per-session context management.

Enables each Cursor chat to have independent state while sharing
a single MCP server process.

Architecture:
- WorkspaceState: Represents a Cursor workspace (folder)
- ChatSession: Represents an individual chat session within a workspace
- WorkspaceRegistry: Manages all workspaces and sessions

The MCP protocol provides `ctx.session.list_roots()` which returns the
workspace path(s) open in Cursor. We use this as a "workspace identifier".

Since MCP doesn't provide a unique chat ID, we generate session IDs when
`session_start()` is called. Multiple sessions can exist per workspace.

Persistence:
- Sessions are persisted to ~/.config/aa-workflow/workspace_states.json
- On server startup, sessions are restored from the persisted file
- This ensures sessions survive server restarts

Usage:
    from server.workspace_state import WorkspaceRegistry, ChatSession

    # In a tool function
    workspace = await WorkspaceRegistry.get_for_ctx(ctx)
    session = workspace.get_active_session()

    # Or create a new session
    session = workspace.create_session()

The implementation is split across ``chat_session``, ``workspace_model``,
``workspace_sync``, ``workspace_persistence``, ``workspace_defaults``,
``cursor_chat_db`` and ``cursor_chat_scan``; this module holds the registry
and re-exports the public names.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from mcp.shared.exceptions import MCPError

from server import cursor_chat_db, utils, workspace_persistence
from server.chat_session import ChatSession
from server.cursor_chat_db import (
    CURSOR_DB_ERRORS,
    _cursor_workspace_storage,
    get_cursor_chat_id_from_db,
    get_cursor_chat_ids,
    get_cursor_chat_info_from_db,
    get_cursor_chat_names,
    inject_context_to_cursor_chat,
    list_cursor_chats,
)
from server.cursor_chat_scan import (
    format_session_context_for_jira,
    get_cursor_chat_content,
    get_cursor_chat_issue_keys,
    get_cursor_chat_personas,
    get_cursor_chat_projects,
    get_meeting_transcript_issue_keys,
)
from server.paths import AA_CONFIG_DIR, WORKSPACE_STATES_FILE
from server.workspace_defaults import (
    DEFAULT_PROJECT,
    DEFAULT_WORKSPACE,
    MAX_FILTER_CACHE_SIZE,
    SESSION_STALE_HOURS,
    _persona_tool_counts,
    get_all_persona_tool_counts,
    get_default_persona,
    get_persona_tool_count,
    now,
    update_persona_tool_count,
)
from server.workspace_model import WorkspaceState, _generate_session_id, set_persist_hook

if TYPE_CHECKING:
    from fastmcp import Context

logger = logging.getLogger(__name__)

# Persistence file location - centralized in server.paths
PERSIST_DIR = AA_CONFIG_DIR
PERSIST_FILE = WORKSPACE_STATES_FILE

# Failures from the MCP client when asking for the workspace roots
_LIST_ROOTS_ERRORS: tuple[type[Exception], ...] = (
    MCPError,
    OSError,
    RuntimeError,
    AttributeError,
    TypeError,
    ValueError,
    asyncio.TimeoutError,
)

__all__ = [
    "DEFAULT_PROJECT",
    "DEFAULT_WORKSPACE",
    "MAX_FILTER_CACHE_SIZE",
    "PERSIST_DIR",
    "PERSIST_FILE",
    "SESSION_STALE_HOURS",
    "ChatSession",
    "WorkspaceRegistry",
    "WorkspaceState",
    "_cursor_workspace_storage",
    "_generate_session_id",
    "_persona_tool_counts",
    "detect_project",
    "format_session_context_for_jira",
    "get_all_persona_tool_counts",
    "get_cursor_chat_content",
    "get_cursor_chat_id_from_db",
    "get_cursor_chat_ids",
    "get_cursor_chat_info_from_db",
    "get_cursor_chat_issue_keys",
    "get_cursor_chat_names",
    "get_cursor_chat_personas",
    "get_cursor_chat_projects",
    "get_default_persona",
    "get_meeting_transcript_issue_keys",
    "get_persona_tool_count",
    "get_workspace_state",
    "inject_context_to_cursor_chat",
    "list_cursor_chats",
    "update_persona_tool_count",
]


def _workspace_path(workspace_uri: str) -> Path | None:
    """Resolved local path of a workspace URI (cwd for the default workspace)."""
    try:
        if workspace_uri.startswith("file://"):
            workspace_path = Path(workspace_uri[7:])
        elif workspace_uri == DEFAULT_WORKSPACE:
            # Try current working directory for default workspace
            workspace_path = Path.cwd()
        else:
            workspace_path = Path(workspace_uri)
        return workspace_path.resolve()
    # Best-effort: the directory may be gone or unreadable.
    except (OSError, RuntimeError, ValueError):
        return None


def _project_containing(workspace_path: Path, repositories: dict) -> str | None:
    """First configured project whose path is the workspace or one of its parents."""
    for project_name, project_config in repositories.items():
        project_path_str = project_config.get("path", "")
        if not project_path_str:
            continue
        try:
            workspace_path.relative_to(Path(project_path_str).expanduser().resolve())
        # Not under this project (ValueError), or its path cannot be resolved.
        except (ValueError, OSError, RuntimeError):
            continue
        return project_name
    return None


def _sum_results(totals: dict, result: dict) -> None:
    """Add one workspace's sync counts to the totals."""
    totals["added"] += result["added"]
    totals["removed"] += result["removed"]
    totals["renamed"] += result["renamed"]
    totals["updated"] += result.get("updated", 0)


def detect_project(workspace_uri: str) -> str | None:
    """Detect project from workspace URI by matching against config.json.

    Args:
        workspace_uri: Workspace URI (file:// or path)

    Returns:
        Project name if found, None otherwise
    """
    config = utils.load_config()
    if not config:
        return None

    workspace_path = _workspace_path(workspace_uri)
    if workspace_path is None:
        return None
    return _project_containing(workspace_path, config.get("repositories", {}))


class WorkspaceRegistry:
    """Registry of workspace states.

    Singleton-like class that manages all workspace states. Each workspace
    is identified by its URI from MCP's list_roots().

    Thread-safe for concurrent access from multiple tool calls.
    """

    _workspaces: ClassVar[dict[str, WorkspaceState]] = {}
    _access_count: ClassVar[int] = 0  # Counter for periodic cleanup
    _CLEANUP_INTERVAL: ClassVar[int] = 100  # Run cleanup every N accesses

    @classmethod
    async def get_for_ctx(cls, ctx: "Context", ensure_session: bool = True) -> WorkspaceState:
        """Get or create workspace state from MCP context.

        Args:
            ctx: MCP Context from tool call
            ensure_session: If True, auto-create a session if none exists

        Returns:
            WorkspaceState for the current workspace
        """
        logger.debug(
            "get_for_ctx called, current registry has %s workspace(s)",
            len(cls._workspaces),
        )

        # Periodic cleanup to prevent memory leaks
        cls._access_count += 1
        if cls._access_count >= cls._CLEANUP_INTERVAL:
            cls._access_count = 0
            cleaned = cls.cleanup_stale(max_age_hours=SESSION_STALE_HOURS)
            if cleaned > 0:
                logger.info("Periodic cleanup: removed %s stale workspace(s)", cleaned)

        workspace_uri = await cls._get_workspace_uri(ctx)
        logger.debug("Resolved workspace_uri: %s", workspace_uri)

        is_new_workspace = workspace_uri not in cls._workspaces

        if is_new_workspace:
            # Try to restore from disk first (in case server restarted)
            # This handles the case where restore_if_empty was called but
            # the workspace URI didn't match any persisted workspaces
            cls.try_restore_workspace_from_disk(workspace_uri)

            # Check again after potential restore
            if workspace_uri in cls._workspaces:
                logger.info("Restored workspace %s from disk", workspace_uri)
                is_new_workspace = False
            else:
                # Create new workspace state
                state = WorkspaceState(workspace_uri=workspace_uri)

                # Auto-detect project from workspace path
                detected_project = detect_project(workspace_uri)
                if detected_project:
                    state.project = detected_project
                    state.is_auto_detected = True
                    logger.info(
                        "Auto-detected project '%s' for workspace %s",
                        detected_project,
                        workspace_uri,
                    )

                cls._workspaces[workspace_uri] = state
                logger.info(
                    "Created new workspace state for %s, registry now has %s workspace(s)",
                    workspace_uri,
                    len(cls._workspaces),
                )
        else:
            logger.debug("Found existing workspace state for %s", workspace_uri)
            cls._workspaces[workspace_uri].touch()

        workspace = cls._workspaces[workspace_uri]

        # Auto-create session if none exists and ensure_session is True
        if ensure_session and not workspace.get_active_session():
            logger.info("No active session in workspace %s, auto-creating one", workspace_uri)
            session = workspace.create_session(name="Auto-created")
            logger.info(
                "Auto-created session %s for workspace %s",
                session.session_id,
                workspace_uri,
            )

        return workspace

    @classmethod
    async def _get_workspace_uri(cls, ctx: "Context") -> str:
        """Extract workspace URI from MCP context.

        Uses ctx.session.list_roots() to get the workspace path(s).
        Falls back to "default" if unavailable.

        Args:
            ctx: MCP Context

        Returns:
            Workspace URI string
        """
        try:
            # Check if session has list_roots method
            if not hasattr(ctx, "session") or ctx.session is None:
                logger.info("No session in context, using default workspace")
                return DEFAULT_WORKSPACE

            logger.info("Calling list_roots()...")
            roots_result = await ctx.session.list_roots()
            logger.info("list_roots() returned: %s", roots_result)

            if roots_result and hasattr(roots_result, "roots") and roots_result.roots:
                # Use the first root as the workspace identifier
                root = roots_result.roots[0]
                uri = str(root.uri) if hasattr(root, "uri") else str(root)
                logger.info("Got workspace URI from list_roots: %s", uri)
                return uri
            logger.info("list_roots() returned empty or no roots")

        # Best-effort: the client may not support roots.
        except _LIST_ROOTS_ERRORS as e:
            logger.info("Failed to get workspace from list_roots: %s", e)

        logger.info("Falling back to DEFAULT_WORKSPACE")
        return DEFAULT_WORKSPACE

    @classmethod
    def _read_persisted(cls) -> dict | None:
        """Persisted workspaces (version 2 format), or None when absent or older."""
        with open(PERSIST_FILE, encoding="utf-8") as f:
            data = json.load(f)
        logger.info("load_from_disk: File contains %s workspace(s)", len(data.get("workspaces", {})))
        version = data.get("version", 1)
        if version < 2:
            logger.warning("Old persist format version %s, skipping restore", version)
            return None
        return data.get("workspaces", {})

    @classmethod
    def try_restore_workspace_from_disk(cls, workspace_uri: str) -> bool:
        """Try to restore a specific workspace from the persisted file.

        This is called when a workspace URI is not found in memory but might
        exist in the persisted file (e.g., after server restart).

        Args:
            workspace_uri: Workspace URI to restore

        Returns:
            True if workspace was restored, False otherwise
        """
        if not PERSIST_FILE.exists():
            return False

        try:
            workspaces_data = cls._read_persisted()
            if workspaces_data is None:
                return False

            # Also accept the URI with/without a trailing slash
            persisted_uri = workspace_persistence.find_persisted_uri(workspace_uri, workspaces_data)
            if persisted_uri is None:
                return False
            workspace_uri = persisted_uri

            ws_data = workspaces_data[workspace_uri]
            workspace = workspace_persistence.workspace_from_dict(
                workspace_uri, ws_data, ws_data.get("project"), ws_data.get("is_auto_detected", False)
            )

            cls._workspaces[workspace_uri] = workspace
            logger.info(
                "Restored workspace %s with %s session(s) from disk",
                workspace_uri,
                len(workspace.sessions),
            )
            return True

        # Best-effort: log and continue.
        except CURSOR_DB_ERRORS as e:
            logger.warning("Failed to restore workspace %s from disk: %s", workspace_uri, e)
            return False

    @classmethod
    def get(cls, workspace_uri: str) -> WorkspaceState | None:
        """Get workspace state by URI (synchronous).

        Args:
            workspace_uri: Workspace URI

        Returns:
            WorkspaceState if exists, None otherwise
        """
        return cls._workspaces.get(workspace_uri)

    @classmethod
    def get_or_create(cls, workspace_uri: str, ensure_session: bool = True) -> WorkspaceState:
        """Get or create workspace state by URI (synchronous).

        Args:
            workspace_uri: Workspace URI
            ensure_session: If True, auto-create a session if none exists

        Returns:
            WorkspaceState for the workspace
        """
        if workspace_uri not in cls._workspaces:
            state = WorkspaceState(workspace_uri=workspace_uri)
            detected_project = detect_project(workspace_uri)
            if detected_project:
                state.project = detected_project
                state.is_auto_detected = True
            cls._workspaces[workspace_uri] = state

        workspace = cls._workspaces[workspace_uri]

        # Auto-create session if none exists and ensure_session is True
        if ensure_session and not workspace.get_active_session():
            logger.info("No active session in workspace %s, auto-creating one", workspace_uri)
            session = workspace.create_session(name="Auto-created")
            logger.info(
                "Auto-created session %s for workspace %s",
                session.session_id,
                workspace_uri,
            )

        return workspace

    @classmethod
    def get_all(cls) -> dict[str, WorkspaceState]:
        """Get all workspace states.

        Returns:
            Dictionary of workspace_uri -> WorkspaceState
        """
        return cls._workspaces.copy()

    @classmethod
    def get_all_as_dict(cls) -> dict[str, dict[str, Any]]:
        """Get all workspace states as serializable dictionaries.

        Useful for exporting to VS Code extension.

        Returns:
            Dictionary of workspace_uri -> state dict
        """
        return {uri: state.to_dict() for uri, state in cls._workspaces.items()}

    @classmethod
    def get_all_sessions(cls) -> list[dict[str, Any]]:
        """Get all sessions across all workspaces.

        Returns:
            List of session dicts with workspace info
        """
        sessions = []
        for workspace in cls._workspaces.values():
            for session_id, session in workspace.sessions.items():
                session_dict = session.to_dict()
                # Use session's own project if set, otherwise fall back to workspace project
                # This preserves per-session project assignments
                if session_dict.get("project") is None:
                    session_dict["project"] = workspace.project
                session_dict["is_active"] = session_id == workspace.active_session_id
                sessions.append(session_dict)
        return sessions

    @classmethod
    def total_session_count(cls) -> int:
        """Get total number of sessions across all workspaces."""
        return sum(ws.session_count() for ws in cls._workspaces.values())

    @classmethod
    def sync_all_with_cursor(cls, skip_content_scan: bool = False) -> dict:
        """Full sync with Cursor's database for all workspaces.

        This should be called before exporting workspace state to ensure
        sessions are in sync with Cursor's database (adds, removes, renames, updates).

        Args:
            skip_content_scan: If True, skip expensive content scanning (issue keys,
                              personas, projects). Useful for initial sync.

        Returns:
            Dict with total counts: {"added": N, "removed": N, "renamed": N, "updated": N}
        """
        totals = {"added": 0, "removed": 0, "renamed": 0, "updated": 0}

        for workspace in cls._workspaces.values():
            result = workspace.sync_with_cursor_db(skip_content_scan=skip_content_scan)
            totals["added"] += result["added"]
            totals["removed"] += result["removed"]
            totals["renamed"] += result["renamed"]
            totals["updated"] += result.get("updated", 0)

        total_changes = sum(totals.values())
        if total_changes > 0:
            logger.info(
                "Synced all workspaces with Cursor DB: +%s -%s ~%s ↻%s",
                totals["added"],
                totals["removed"],
                totals["renamed"],
                totals["updated"],
            )
            # Persist changes to disk
            cls.save_to_disk()

        return totals

    @classmethod
    def sync_all_session_names(cls) -> int:
        """Deprecated: Use sync_all_with_cursor() instead."""
        result = cls.sync_all_with_cursor()
        return result["renamed"]

    @classmethod
    def sync_sessions_with_cursor(cls, session_ids: list[str] | None = None) -> dict:
        """Sync specific sessions with Cursor's database.

        This is more efficient than sync_all_with_cursor when you only need
        to update a subset of sessions (e.g., recently active ones).

        Args:
            session_ids: List of session IDs to sync. If None, syncs all sessions.

        Returns:
            Dict with total counts: {"added": N, "removed": N, "renamed": N, "updated": N}
        """
        if session_ids is None:
            # Fall back to full sync
            return cls.sync_all_with_cursor()

        totals = {"added": 0, "removed": 0, "renamed": 0, "updated": 0}

        # Find which workspaces contain the target sessions
        target_workspaces: dict[str, set[str]] = {}  # workspace_uri -> session_ids
        for workspace in cls._workspaces.values():
            matching_ids = set(session_ids) & set(workspace.sessions.keys())
            if matching_ids:
                target_workspaces[workspace.workspace_uri] = matching_ids

        # Sync only the relevant workspaces, passing the target session IDs
        for workspace_uri, target_ids in target_workspaces.items():
            target_state = cls._workspaces.get(workspace_uri)
            if target_state:
                result = target_state.sync_with_cursor_db(session_ids=list(target_ids))
                totals["added"] += result["added"]
                totals["removed"] += result["removed"]
                totals["renamed"] += result["renamed"]
                totals["updated"] += result.get("updated", 0)

        total_changes = sum(totals.values())
        if total_changes > 0:
            logger.debug(
                "Synced %s sessions with Cursor DB: +%s -%s ~%s ↻%s",
                len(session_ids),
                totals["added"],
                totals["removed"],
                totals["renamed"],
                totals["updated"],
            )
            # Persist changes to disk
            cls.save_to_disk()

        return totals

    @classmethod
    def remove(cls, workspace_uri: str) -> bool:
        """Remove a workspace state.

        Args:
            workspace_uri: Workspace URI to remove

        Returns:
            True if removed, False if not found
        """
        if workspace_uri in cls._workspaces:
            del cls._workspaces[workspace_uri]
            logger.debug("Removed workspace state for %s", workspace_uri)
            return True
        return False

    @classmethod
    def remove_session(cls, workspace_uri: str, session_id: str) -> bool:
        """Remove a specific session from a workspace.

        Args:
            workspace_uri: Workspace URI
            session_id: Session ID to remove

        Returns:
            True if removed, False if not found
        """
        workspace = cls._workspaces.get(workspace_uri)
        if workspace:
            return workspace.remove_session(session_id)
        return False

    @classmethod
    def clear(cls) -> None:
        """Clear all workspace states.

        Primarily for testing.
        """
        cls._workspaces.clear()
        logger.debug("Cleared all workspace states")

    @classmethod
    def count(cls) -> int:
        """Get number of active workspaces.

        Returns:
            Number of workspace states
        """
        return len(cls._workspaces)

    @classmethod
    def cleanup_stale(cls, max_age_hours: int = 24) -> int:
        """Remove stale workspaces that haven't been active.

        Also cleans up stale sessions within active workspaces.

        Args:
            max_age_hours: Maximum hours of inactivity before removal

        Returns:
            Number of workspaces removed
        """
        # First, cleanup stale sessions in each workspace
        for workspace in cls._workspaces.values():
            workspace.cleanup_stale_sessions(SESSION_STALE_HOURS)

        # Then cleanup stale workspaces (no sessions and no activity)
        stale_uris = [
            uri
            for uri, state in cls._workspaces.items()
            if state.is_stale(max_age_hours) and state.session_count() == 0
        ]

        for uri in stale_uris:
            del cls._workspaces[uri]
            logger.info("Cleaned up stale workspace: %s", uri)

        if stale_uris:
            logger.info("Cleaned up %s stale workspace(s)", len(stale_uris))

        return len(stale_uris)

    @classmethod
    def touch(cls, workspace_uri: str) -> None:
        """Update last activity for a workspace.

        Call this when a tool is invoked to keep workspace alive.

        Args:
            workspace_uri: Workspace URI to touch
        """
        if workspace_uri in cls._workspaces:
            cls._workspaces[workspace_uri].touch()

    @classmethod
    def save_to_disk(cls) -> bool:
        """Persist all workspace states to disk.

        Called after session changes to ensure persistence across server restarts.

        Returns:
            True if saved successfully, False otherwise.
        """
        try:
            PERSIST_DIR.mkdir(parents=True, exist_ok=True)

            all_workspaces = cls.get_all_as_dict()
            all_sessions = cls.get_all_sessions()

            total_sessions = sum(len(ws.get("sessions", {})) for ws in all_workspaces.values())
            logger.info(
                "save_to_disk: saving %s workspace(s) with %s session(s)",
                len(all_workspaces),
                total_sessions,
            )
            for uri, ws in all_workspaces.items():
                session_ids = list(ws.get("sessions", {}).keys())
                logger.info("  - %s: %s sessions: %s", uri, len(session_ids), session_ids)

            export_data = {
                "version": 2,
                "saved_at": now().isoformat(),
                "workspaces": all_workspaces,
                "sessions": all_sessions,
            }

            with open(PERSIST_FILE, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, default=str)

            logger.info("save_to_disk: successfully saved to %s", PERSIST_FILE)
            return True
        # Best-effort: log and continue.
        except CURSOR_DB_ERRORS as e:
            logger.error("Failed to save workspace state: %s", e)
            return False

    @classmethod
    def _restore_persisted_workspace(cls, workspace_uri: str, ws_data: dict) -> WorkspaceState:
        """Rebuild one persisted workspace, re-detecting its project from the URI."""
        persisted_project = ws_data.get("project")
        detected_project = detect_project(workspace_uri)
        if detected_project and detected_project != persisted_project:
            logger.info(
                "Re-detected project '%s' for workspace %s (was '%s')",
                detected_project,
                workspace_uri,
                persisted_project,
            )
        # A detected project matches the workspace URI; the persisted one may be stale
        return workspace_persistence.workspace_from_dict(
            workspace_uri,
            ws_data,
            detected_project or persisted_project,
            True if detected_project else ws_data.get("is_auto_detected", False),
        )

    @staticmethod
    def _apply_cursor_names(workspace: WorkspaceState) -> None:
        """Take the active chat and changed chat names from Cursor's database."""
        cursor_chats, cursor_active_id = cursor_chat_db.list_cursor_chats(workspace.workspace_uri)
        cursor_chat_map = {c["composerId"]: c for c in cursor_chats}

        if cursor_active_id and cursor_active_id in workspace.sessions:
            workspace.active_session_id = cursor_active_id
        for session_id, session in workspace.sessions.items():
            if session_id not in cursor_chat_map:
                continue
            cursor_name = cursor_chat_map[session_id].get("name")
            if cursor_name and cursor_name != session.name:
                logger.info("Updating session %s name from '%s' to '%s'", session_id, session.name, cursor_name)
                session.name = cursor_name

    @classmethod
    def load_from_disk(cls) -> int:
        """Restore workspace states from disk.

        Called on server startup to restore sessions from previous run.

        Returns:
            Number of sessions restored.
        """
        if not PERSIST_FILE.exists():
            logger.debug("load_from_disk: No persisted workspace state found")
            return 0

        logger.debug("load_from_disk: Loading from %s", PERSIST_FILE)

        try:
            workspaces_data = cls._read_persisted()
            if workspaces_data is None:
                return 0

            restored_sessions = 0
            for workspace_uri, ws_data in workspaces_data.items():
                workspace = cls._restore_persisted_workspace(workspace_uri, ws_data)
                restored_sessions += len(workspace.sessions)
                cls._apply_cursor_names(workspace)

                # Only add workspace if it has sessions or is recent
                if workspace.sessions or not workspace.is_stale(max_age_hours=24):
                    cls._workspaces[workspace_uri] = workspace

            logger.info(
                "Restored %s session(s) from %s workspace(s)",
                restored_sessions,
                len(cls._workspaces),
            )
            return restored_sessions

        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in persist file: %s", e)
            return 0
        # Best-effort: log and continue.
        except CURSOR_DB_ERRORS:
            logger.exception("Failed to load workspace state")
            return 0

    @classmethod
    def restore_if_empty(cls) -> int:
        """Restore from disk only if registry is empty.

        Safe to call multiple times - only loads if no workspaces exist.

        Returns:
            Number of sessions restored (0 if already had workspaces).
        """
        if cls._workspaces:
            total_sessions = sum(ws.session_count() for ws in cls._workspaces.values())
            logger.info(
                "restore_if_empty: Registry already has %s workspace(s) with %s session(s), skipping restore",
                len(cls._workspaces),
                total_sessions,
            )
            return 0
        logger.info("restore_if_empty: Registry is empty, loading from disk")
        return cls.load_from_disk()


# Convenience function for getting workspace state
async def get_workspace_state(ctx: "Context") -> WorkspaceState:
    """Get workspace state from context.

    Convenience function that wraps WorkspaceRegistry.get_for_ctx().

    Args:
        ctx: MCP Context

    Returns:
        WorkspaceState for the current workspace
    """
    return await WorkspaceRegistry.get_for_ctx(ctx)


# Session changes made through WorkspaceState are persisted by the registry
def _persist_registry() -> None:
    """Persist hook for :mod:`server.workspace_model` (looked up at call time)."""
    WorkspaceRegistry.save_to_disk()


set_persist_hook(_persist_registry)
