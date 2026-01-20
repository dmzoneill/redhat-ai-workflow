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
- Sessions are persisted to ~/.mcp/workspace_states/workspace_states.json
- On server startup, sessions are restored from the persisted file
- This ensures sessions survive server restarts

Usage:
    from server.workspace_state import WorkspaceRegistry, ChatSession

    # In a tool function
    workspace = await WorkspaceRegistry.get_for_ctx(ctx)
    session = workspace.get_active_session()

    # Or create a new session
    session = workspace.create_session()
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

logger = logging.getLogger(__name__)

# Default workspace key when list_roots() is unavailable
DEFAULT_WORKSPACE = "default"

# Default project when none detected
DEFAULT_PROJECT = "redhat-ai-workflow"

# Session stale timeout (hours) - sessions inactive for longer are cleaned up
SESSION_STALE_HOURS = 24

# Persistence file location
PERSIST_DIR = Path.home() / ".mcp" / "workspace_states"
PERSIST_FILE = PERSIST_DIR / "workspace_states.json"

# Global cache of tool counts per persona (refreshed on session_start/persona_load)
_persona_tool_counts: dict[str, int] = {}


def get_persona_tool_count(persona: str) -> int:
    """Get cached tool count for a persona."""
    return _persona_tool_counts.get(persona, 0)


def update_persona_tool_count(persona: str, count: int) -> None:
    """Update the cached tool count for a persona."""
    _persona_tool_counts[persona] = count
    logger.debug(f"Updated persona tool count cache: {persona} = {count}")


def get_all_persona_tool_counts() -> dict[str, int]:
    """Get all cached persona tool counts."""
    return _persona_tool_counts.copy()


def _generate_session_id() -> str:
    """Generate a unique session ID (fallback only)."""
    return str(uuid.uuid4())


def get_cursor_chat_info_from_db(workspace_uri: str) -> tuple[str | None, str | None]:
    """Read Cursor's database to get the current chat's UUID and name.

    Cursor stores chat data in workspace-specific SQLite databases.
    We find the most recently updated chat for this workspace and return its ID and name.

    Args:
        workspace_uri: The workspace URI (e.g., "file:///home/user/project")

    Returns:
        Tuple of (chat_id, chat_name) if found, (None, None) otherwise
    """
    import subprocess

    try:
        workspace_storage_dir = Path.home() / ".config" / "Cursor" / "User" / "workspaceStorage"

        if not workspace_storage_dir.exists():
            logger.debug("Cursor workspace storage not found")
            return None, None

        # Find the workspace storage folder matching our workspace
        for storage_dir in workspace_storage_dir.iterdir():
            if not storage_dir.is_dir():
                continue

            workspace_json = storage_dir / "workspace.json"
            if not workspace_json.exists():
                continue

            try:
                import json

                workspace_data = json.loads(workspace_json.read_text())
                folder_uri = workspace_data.get("folder", "")

                # Check if this matches our workspace
                if folder_uri == workspace_uri:
                    # Found it! Now read the composer data
                    db_path = storage_dir / "state.vscdb"
                    if not db_path.exists():
                        continue

                    # Query the database for composer data
                    query = "SELECT value FROM ItemTable WHERE key = 'composer.composerData'"
                    result = subprocess.run(["sqlite3", str(db_path), query], capture_output=True, text=True, timeout=5)

                    if result.returncode != 0 or not result.stdout.strip():
                        logger.debug(f"No composer data in {db_path}")
                        return None, None

                    composer_data = json.loads(result.stdout.strip())
                    all_composers = composer_data.get("allComposers", [])

                    if not all_composers:
                        logger.debug("No composers found in database")
                        return None, None

                    # Filter out archived/draft chats and sort by lastUpdatedAt
                    active_chats = [c for c in all_composers if not c.get("isArchived") and not c.get("isDraft")]

                    if not active_chats:
                        logger.debug("No active chats found")
                        return None, None

                    # Get the most recently updated chat (likely the current one)
                    most_recent = max(active_chats, key=lambda x: x.get("lastUpdatedAt", 0))
                    chat_id = most_recent.get("composerId")
                    chat_name = most_recent.get("name")

                    logger.info(f"Found Cursor chat: {chat_id} ({chat_name})")
                    return chat_id, chat_name

            except (json.JSONDecodeError, KeyError) as e:
                logger.debug(f"Error parsing workspace.json in {storage_dir}: {e}")
                continue

        logger.debug(f"No matching workspace storage found for {workspace_uri}")
        return None, None

    except Exception as e:
        logger.warning(f"Error reading Cursor database: {e}")
        return None, None


def get_cursor_chat_id_from_db(workspace_uri: str) -> str | None:
    """Read Cursor's database to get the current chat's UUID (backward compat wrapper).

    Args:
        workspace_uri: The workspace URI

    Returns:
        The Cursor chat UUID if found, None otherwise
    """
    chat_id, _ = get_cursor_chat_info_from_db(workspace_uri)
    return chat_id


def list_cursor_chats(workspace_uri: str) -> list[dict]:
    """List all Cursor chats for a workspace.

    Args:
        workspace_uri: The workspace URI

    Returns:
        List of chat info dicts with composerId, name, createdAt, lastUpdatedAt
    """
    import subprocess

    try:
        workspace_storage_dir = Path.home() / ".config" / "Cursor" / "User" / "workspaceStorage"

        if not workspace_storage_dir.exists():
            return []

        for storage_dir in workspace_storage_dir.iterdir():
            if not storage_dir.is_dir():
                continue

            workspace_json = storage_dir / "workspace.json"
            if not workspace_json.exists():
                continue

            try:
                import json

                workspace_data = json.loads(workspace_json.read_text())
                folder_uri = workspace_data.get("folder", "")

                if folder_uri == workspace_uri:
                    db_path = storage_dir / "state.vscdb"
                    if not db_path.exists():
                        continue

                    query = "SELECT value FROM ItemTable WHERE key = 'composer.composerData'"
                    result = subprocess.run(["sqlite3", str(db_path), query], capture_output=True, text=True, timeout=5)

                    if result.returncode != 0 or not result.stdout.strip():
                        return []

                    composer_data = json.loads(result.stdout.strip())
                    all_composers = composer_data.get("allComposers", [])

                    # Return relevant fields for active chats, sorted by lastUpdatedAt
                    chats = [
                        {
                            "composerId": c.get("composerId"),
                            "name": c.get("name", "unnamed"),
                            "createdAt": c.get("createdAt", 0),
                            "lastUpdatedAt": c.get("lastUpdatedAt", 0),
                            "isArchived": c.get("isArchived", False),
                            "isDraft": c.get("isDraft", False),
                        }
                        for c in all_composers
                        if not c.get("isArchived") and not c.get("isDraft")
                    ]
                    return sorted(chats, key=lambda x: x["lastUpdatedAt"], reverse=True)

            except (json.JSONDecodeError, KeyError):
                continue

        return []

    except Exception as e:
        logger.warning(f"Error listing Cursor chats: {e}")
        return []


def get_cursor_chat_ids(workspace_uri: str) -> set[str]:
    """Get all active Cursor chat IDs for a workspace.

    Args:
        workspace_uri: The workspace URI

    Returns:
        Set of chat IDs that exist in Cursor's database
    """
    chats = list_cursor_chats(workspace_uri)
    return {c["composerId"] for c in chats if c.get("composerId")}


def get_cursor_chat_names(workspace_uri: str) -> dict[str, str]:
    """Get a mapping of Cursor chat IDs to their names.

    Args:
        workspace_uri: The workspace URI

    Returns:
        Dict mapping chat ID to chat name
    """
    chats = list_cursor_chats(workspace_uri)
    return {c["composerId"]: c.get("name") for c in chats if c.get("composerId")}


@dataclass
class ChatSession:
    """State for a single chat session within a workspace.

    Each chat session maintains its own:
    - Session ID (generated on session_start())
    - Project (per-session, not per-workspace!)
    - Persona (developer, devops, incident, release)
    - Active issue and branch
    - Tool filter cache (for NPU results)
    """

    session_id: str
    workspace_uri: str
    persona: str = "developer"
    project: str | None = None  # Per-session project (can differ from workspace default)
    is_project_auto_detected: bool = False  # True if project was auto-detected from workspace path
    issue_key: str | None = None
    branch: str | None = None
    tool_count: int = 0  # Number of tools loaded for this session's persona
    started_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)

    # NPU tool filtering cache (keyed by message hash)
    tool_filter_cache: dict[str, list[str]] = field(default_factory=dict)

    # Session metadata
    name: str | None = None  # Optional user-friendly name

    # Activity tracking
    last_tool: str | None = None  # Last tool called in this session
    last_tool_time: datetime | None = None  # When the last tool was called
    tool_call_count: int = 0  # Total tool calls in this session

    # Backward compatibility property
    @property
    def active_tools(self) -> set[str]:
        """Deprecated: Use tool_count instead. Returns empty set for compatibility."""
        return set()

    @active_tools.setter
    def active_tools(self, value: set[str]) -> None:
        """Deprecated: Sets tool_count from the length of the provided set."""
        self.tool_count = len(value) if value else 0

    def touch(self, tool_name: str | None = None) -> None:
        """Update last activity timestamp and optionally track tool call.

        Args:
            tool_name: Optional name of the tool that was called
        """
        self.last_activity = datetime.now()
        if tool_name:
            self.last_tool = tool_name
            self.last_tool_time = datetime.now()
            self.tool_call_count += 1

    def is_stale(self, max_age_hours: int = SESSION_STALE_HOURS) -> bool:
        """Check if session is stale (no activity for max_age_hours).

        Args:
            max_age_hours: Maximum hours of inactivity before considered stale

        Returns:
            True if session is stale
        """
        age = datetime.now() - self.last_activity
        return age.total_seconds() > (max_age_hours * 3600)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "workspace_uri": self.workspace_uri,
            "persona": self.persona,
            "project": self.project,
            "is_project_auto_detected": self.is_project_auto_detected,
            "issue_key": self.issue_key,
            "branch": self.branch,
            "tool_count": self.tool_count,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "name": self.name,
            "last_tool": self.last_tool,
            "last_tool_time": self.last_tool_time.isoformat() if self.last_tool_time else None,
            "tool_call_count": self.tool_call_count,
        }

    def clear_filter_cache(self) -> None:
        """Clear the tool filter cache (e.g., when persona changes)."""
        self.tool_filter_cache.clear()


@dataclass
class WorkspaceState:
    """State for a Cursor workspace (folder).

    A workspace can have multiple chat sessions. The workspace tracks:
    - Project context (which codebase) - shared across sessions
    - Active sessions (each chat is a session)
    - Currently active session ID
    """

    workspace_uri: str
    project: str | None = None
    sessions: dict[str, ChatSession] = field(default_factory=dict)
    active_session_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)

    # Metadata
    is_auto_detected: bool = False  # True if project was auto-detected from path

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.now()

    def is_stale(self, max_age_hours: int = 24) -> bool:
        """Check if workspace is stale (no activity for max_age_hours).

        Args:
            max_age_hours: Maximum hours of inactivity before considered stale

        Returns:
            True if workspace is stale
        """
        age = datetime.now() - self.last_activity
        return age.total_seconds() > (max_age_hours * 3600)

    def create_session(
        self,
        persona: str = "developer",
        name: str | None = None,
        project: str | None = None,
        is_project_auto_detected: bool = False,
        session_id: str | None = None,
    ) -> ChatSession:
        """Create a new chat session in this workspace.

        Args:
            persona: Initial persona for the session
            name: Optional user-friendly name
            project: Optional project for this session (defaults to workspace project if not set)
            is_project_auto_detected: Whether the project was auto-detected from workspace path
            session_id: Optional session ID (uses Cursor's chat UUID if available)

        Returns:
            The newly created ChatSession
        """
        # Try to get Cursor's chat UUID and name if no session_id provided
        cursor_chat_name = None
        if session_id is None:
            cursor_chat_id, cursor_chat_name = get_cursor_chat_info_from_db(self.workspace_uri)
            if cursor_chat_id:
                session_id = cursor_chat_id
                logger.info(f"Using Cursor chat ID as session ID: {session_id} ({cursor_chat_name})")
            else:
                session_id = _generate_session_id()
                logger.info(f"Generated fallback session ID: {session_id}")

        # Use Cursor's chat name if no name provided
        if name is None and cursor_chat_name:
            name = cursor_chat_name

        # Get tool count from currently loaded tools
        loaded_tools = self._get_loaded_tools()
        tool_count = len(loaded_tools)

        # Use workspace project as default if no project specified
        session_project = project if project is not None else self.project
        session_auto_detected = is_project_auto_detected if project is not None else self.is_auto_detected

        session = ChatSession(
            session_id=session_id,
            workspace_uri=self.workspace_uri,
            persona=persona,
            project=session_project,
            is_project_auto_detected=session_auto_detected,
            tool_count=tool_count,
            name=name,
        )

        self.sessions[session_id] = session
        self.active_session_id = session_id
        self.touch()

        logger.info(f"Created session {session_id} in workspace {self.workspace_uri} with project '{session_project}'")

        # #region agent log
        import json as _debug_json  # noqa: F811

        open("/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log", "a").write(
            _debug_json.dumps(
                {
                    "location": "workspace_state.py:create_session",
                    "message": "Created new session with per-session project",
                    "data": {
                        "session_id": session_id,
                        "session_project": session_project,
                        "is_auto_detected": session_auto_detected,
                        "workspace_project": self.project,
                        "explicit_project_arg": project,
                    },
                    "timestamp": __import__("time").time() * 1000,
                    "sessionId": "debug-session",
                    "hypothesisId": "per-session",
                }
            )
            + "\n"
        )
        # #endregion

        # Persist to disk after creating session
        WorkspaceRegistry.save_to_disk()

        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        """Get a session by ID.

        Args:
            session_id: Session ID to look up

        Returns:
            ChatSession if found, None otherwise
        """
        return self.sessions.get(session_id)

    def get_active_session(self, refresh_tools: bool = True) -> ChatSession | None:
        """Get the currently active session.

        Args:
            refresh_tools: If True and session has no tools, try to refresh from PersonaLoader

        Returns:
            Active ChatSession or None if no active session
        """
        if self.active_session_id:
            session = self.sessions.get(self.active_session_id)
            # Refresh tool count if zero (e.g., after restore from disk)
            if session and refresh_tools and session.tool_count == 0:
                session.tool_count = len(self._get_loaded_tools())
            return session
        return None

    def get_or_create_session(self, persona: str = "developer") -> ChatSession:
        """Get active session or create a new one.

        Args:
            persona: Persona to use if creating new session

        Returns:
            Active or newly created ChatSession
        """
        session = self.get_active_session()
        if session:
            session.touch()
            return session
        return self.create_session(persona=persona)

    def set_active_session(self, session_id: str) -> bool:
        """Set the active session.

        Args:
            session_id: Session ID to make active

        Returns:
            True if session exists and was set active, False otherwise
        """
        if session_id in self.sessions:
            self.active_session_id = session_id
            self.sessions[session_id].touch()
            self.touch()
            return True
        return False

    def remove_session(self, session_id: str) -> bool:
        """Remove a session.

        Args:
            session_id: Session ID to remove

        Returns:
            True if removed, False if not found
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            if self.active_session_id == session_id:
                # Set active to most recent remaining session
                if self.sessions:
                    most_recent = max(self.sessions.values(), key=lambda s: s.last_activity)
                    self.active_session_id = most_recent.session_id
                else:
                    self.active_session_id = None
            logger.info(f"Removed session {session_id} from workspace {self.workspace_uri}")

            # Persist to disk after removing session
            WorkspaceRegistry.save_to_disk()

            return True
        return False

    def cleanup_stale_sessions(self, max_age_hours: int = SESSION_STALE_HOURS) -> int:
        """Remove stale sessions that no longer exist in Cursor.

        Sessions are only removed if they are stale AND no longer exist in
        Cursor's database. This ensures we don't lose session data for chats
        that are still open in Cursor.

        Args:
            max_age_hours: Maximum hours of inactivity before considering removal

        Returns:
            Number of sessions removed
        """
        # Get all chat IDs that still exist in Cursor
        cursor_chat_ids = get_cursor_chat_ids(self.workspace_uri)

        # Only remove sessions that are stale AND not in Cursor's database
        stale_ids = [
            sid
            for sid, session in self.sessions.items()
            if session.is_stale(max_age_hours) and sid not in cursor_chat_ids
        ]

        for sid in stale_ids:
            self.remove_session(sid)

        if stale_ids:
            logger.info(f"Cleaned up {len(stale_ids)} stale session(s) not in Cursor DB from {self.workspace_uri}")

        return len(stale_ids)

    def session_count(self) -> int:
        """Get number of sessions in this workspace."""
        return len(self.sessions)

    def sync_session_names_from_cursor(self) -> int:
        """Sync session names from Cursor's database.

        Updates session names to match what's in Cursor's database.
        This ensures the UI shows the correct chat names.

        Returns:
            Number of sessions updated
        """
        cursor_names = get_cursor_chat_names(self.workspace_uri)
        updated = 0

        for session_id, session in self.sessions.items():
            if session_id in cursor_names:
                cursor_name = cursor_names[session_id]
                if cursor_name and cursor_name != session.name:
                    logger.debug(f"Syncing session {session_id} name: '{session.name}' -> '{cursor_name}'")
                    session.name = cursor_name
                    updated += 1

        if updated > 0:
            logger.info(f"Synced {updated} session name(s) from Cursor DB for {self.workspace_uri}")

        return updated

    def _get_loaded_tools(self) -> set[str]:
        """Get currently loaded tool names from PersonaLoader."""
        try:
            from .persona_loader import get_loader

            loader = get_loader()
            if loader:
                # Get actual tool names, not module names
                tools = set(loader._tool_to_module.keys())
                logger.info(f"_get_loaded_tools: found {len(tools)} tools from {len(loader.loaded_modules)} modules")
                return tools
            else:
                logger.warning("_get_loaded_tools: PersonaLoader not initialized")
        except Exception as e:
            logger.warning(f"Could not get loaded tools: {e}")

        return set()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "workspace_uri": self.workspace_uri,
            "project": self.project,
            "is_auto_detected": self.is_auto_detected,
            "active_session_id": self.active_session_id,
            "sessions": {sid: s.to_dict() for sid, s in self.sessions.items()},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
        }

    # Backward compatibility properties - delegate to active session
    @property
    def persona(self) -> str:
        """Get persona from active session (backward compat)."""
        session = self.get_active_session()
        return session.persona if session else "developer"

    @persona.setter
    def persona(self, value: str) -> None:
        """Set persona on active session (backward compat)."""
        session = self.get_active_session()
        if session:
            session.persona = value

    @property
    def issue_key(self) -> str | None:
        """Get issue_key from active session (backward compat)."""
        session = self.get_active_session()
        return session.issue_key if session else None

    @issue_key.setter
    def issue_key(self, value: str | None) -> None:
        """Set issue_key on active session (backward compat)."""
        session = self.get_active_session()
        if session:
            session.issue_key = value

    @property
    def branch(self) -> str | None:
        """Get branch from active session (backward compat)."""
        session = self.get_active_session()
        return session.branch if session else None

    @branch.setter
    def branch(self, value: str | None) -> None:
        """Set branch on active session (backward compat)."""
        session = self.get_active_session()
        if session:
            session.branch = value

    @property
    def active_tools(self) -> set[str]:
        """Get active_tools from active session (backward compat)."""
        session = self.get_active_session()
        return session.active_tools if session else set()

    @active_tools.setter
    def active_tools(self, value: set[str]) -> None:
        """Set active_tools on active session (backward compat)."""
        session = self.get_active_session()
        if session:
            session.active_tools = value

    @property
    def started_at(self) -> datetime | None:
        """Get started_at from active session (backward compat)."""
        session = self.get_active_session()
        return session.started_at if session else self.created_at

    @property
    def tool_filter_cache(self) -> dict[str, list[str]]:
        """Get tool_filter_cache from active session (backward compat)."""
        session = self.get_active_session()
        return session.tool_filter_cache if session else {}

    def clear_filter_cache(self) -> None:
        """Clear filter cache on active session (backward compat)."""
        session = self.get_active_session()
        if session:
            session.clear_filter_cache()


class WorkspaceRegistry:
    """Registry of workspace states.

    Singleton-like class that manages all workspace states. Each workspace
    is identified by its URI from MCP's list_roots().

    Thread-safe for concurrent access from multiple tool calls.
    """

    _workspaces: dict[str, WorkspaceState] = {}

    @classmethod
    async def get_for_ctx(cls, ctx: "Context", ensure_session: bool = True) -> WorkspaceState:
        """Get or create workspace state from MCP context.

        Args:
            ctx: MCP Context from tool call
            ensure_session: If True, auto-create a session if none exists

        Returns:
            WorkspaceState for the current workspace
        """
        # #region agent log
        import json as _debug_json  # noqa: F811

        open("/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log", "a").write(
            _debug_json.dumps(
                {
                    "location": "workspace_state.py:get_for_ctx:entry",
                    "message": "get_for_ctx called",
                    "data": {
                        "registry_count": len(cls._workspaces),
                        "existing_workspaces": list(cls._workspaces.keys()),
                    },
                    "timestamp": __import__("time").time() * 1000,
                    "sessionId": "debug-session",
                    "hypothesisId": "A,E",
                }
            )
            + "\n"
        )
        # #endregion
        logger.info(f"get_for_ctx called, current registry has {len(cls._workspaces)} workspace(s)")
        workspace_uri = await cls._get_workspace_uri(ctx)
        logger.info(f"Resolved workspace_uri: {workspace_uri}")

        is_new_workspace = workspace_uri not in cls._workspaces
        # #region agent log
        import json as _debug_json  # noqa: F811

        open("/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log", "a").write(
            _debug_json.dumps(
                {
                    "location": "workspace_state.py:get_for_ctx:check_new",
                    "message": "Checking if workspace is new",
                    "data": {"workspace_uri": workspace_uri, "is_new_workspace": is_new_workspace},
                    "timestamp": __import__("time").time() * 1000,
                    "sessionId": "debug-session",
                    "hypothesisId": "A,E",
                }
            )
            + "\n"
        )
        # #endregion

        if is_new_workspace:
            # Try to restore from disk first (in case server restarted)
            # This handles the case where restore_if_empty was called but
            # the workspace URI didn't match any persisted workspaces
            cls._try_restore_workspace_from_disk(workspace_uri)

            # Check again after potential restore
            if workspace_uri in cls._workspaces:
                logger.info(f"Restored workspace {workspace_uri} from disk")
                is_new_workspace = False
                # #region agent log
                restored_ws = cls._workspaces[workspace_uri]
                import json as _debug_json  # noqa: F811

                open("/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log", "a").write(
                    _debug_json.dumps(
                        {
                            "location": "workspace_state.py:get_for_ctx:restored",
                            "message": "Restored workspace from disk",
                            "data": {
                                "workspace_uri": workspace_uri,
                                "restored_project": restored_ws.project,
                                "is_auto_detected": restored_ws.is_auto_detected,
                                "session_count": len(restored_ws.sessions),
                            },
                            "timestamp": __import__("time").time() * 1000,
                            "sessionId": "debug-session",
                            "hypothesisId": "E",
                        }
                    )
                    + "\n"
                )
                # #endregion
            else:
                # Create new workspace state
                state = WorkspaceState(workspace_uri=workspace_uri)

                # Auto-detect project from workspace path
                detected_project = cls._detect_project(workspace_uri)
                # #region agent log
                import json as _debug_json  # noqa: F811

                open("/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log", "a").write(
                    _debug_json.dumps(
                        {
                            "location": "workspace_state.py:get_for_ctx:detect",
                            "message": "Auto-detecting project",
                            "data": {"workspace_uri": workspace_uri, "detected_project": detected_project},
                            "timestamp": __import__("time").time() * 1000,
                            "sessionId": "debug-session",
                            "hypothesisId": "B",
                        }
                    )
                    + "\n"
                )
                # #endregion
                if detected_project:
                    state.project = detected_project
                    state.is_auto_detected = True
                    logger.info(f"Auto-detected project '{detected_project}' for workspace {workspace_uri}")

                cls._workspaces[workspace_uri] = state
                logger.info(
                    f"Created new workspace state for {workspace_uri}, "
                    f"registry now has {len(cls._workspaces)} workspace(s)"
                )
        else:
            logger.info(f"Found existing workspace state for {workspace_uri}")
            existing_ws = cls._workspaces[workspace_uri]
            # #region agent log
            import json as _debug_json  # noqa: F811

            open("/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log", "a").write(
                _debug_json.dumps(
                    {
                        "location": "workspace_state.py:get_for_ctx:existing",
                        "message": "Using existing workspace",
                        "data": {
                            "workspace_uri": workspace_uri,
                            "project": existing_ws.project,
                            "is_auto_detected": existing_ws.is_auto_detected,
                            "active_session_id": existing_ws.active_session_id,
                            "session_count": len(existing_ws.sessions),
                        },
                        "timestamp": __import__("time").time() * 1000,
                        "sessionId": "debug-session",
                        "hypothesisId": "A,C",
                    }
                )
                + "\n"
            )
            # #endregion
            cls._workspaces[workspace_uri].touch()

        workspace = cls._workspaces[workspace_uri]

        # Auto-create session if none exists and ensure_session is True
        if ensure_session and not workspace.get_active_session():
            logger.info(f"No active session in workspace {workspace_uri}, auto-creating one")
            session = workspace.create_session(persona="developer", name="Auto-created")
            logger.info(f"Auto-created session {session.session_id} for workspace {workspace_uri}")

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

            # Try to get roots
            logger.info("Calling list_roots()...")
            roots_result = await ctx.session.list_roots()
            logger.info(f"list_roots() returned: {roots_result}")

            if roots_result and hasattr(roots_result, "roots") and roots_result.roots:
                # Use the first root as the workspace identifier
                root = roots_result.roots[0]
                uri = str(root.uri) if hasattr(root, "uri") else str(root)
                logger.info(f"Got workspace URI from list_roots: {uri}")
                return uri
            else:
                logger.info("list_roots() returned empty or no roots")

        except Exception as e:
            logger.info(f"Failed to get workspace from list_roots: {e}")

        logger.info("Falling back to DEFAULT_WORKSPACE")
        return DEFAULT_WORKSPACE

    @classmethod
    def _detect_project(cls, workspace_uri: str) -> str | None:
        """Detect project from workspace URI by matching against config.json.

        Args:
            workspace_uri: Workspace URI (file:// or path)

        Returns:
            Project name if found, None otherwise
        """
        from server.utils import load_config

        config = load_config()
        if not config:
            # #region agent log
            import json as _debug_json  # noqa: F811

            open("/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log", "a").write(
                _debug_json.dumps(
                    {
                        "location": "workspace_state.py:_detect_project:no_config",
                        "message": "No config loaded",
                        "data": {"workspace_uri": workspace_uri},
                        "timestamp": __import__("time").time() * 1000,
                        "sessionId": "debug-session",
                        "hypothesisId": "B",
                    }
                )
                + "\n"
            )
            # #endregion
            return None

        # Convert file:// URI to path
        if workspace_uri.startswith("file://"):
            workspace_path = Path(workspace_uri[7:])
        elif workspace_uri == DEFAULT_WORKSPACE:
            # Try current working directory for default workspace
            try:
                workspace_path = Path.cwd()
            except Exception:
                return None
        else:
            workspace_path = Path(workspace_uri)

        try:
            workspace_path = workspace_path.resolve()
        except Exception:
            return None

        repositories = config.get("repositories", {})
        # #region agent log
        import json as _debug_json  # noqa: F811

        open("/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log", "a").write(
            _debug_json.dumps(
                {
                    "location": "workspace_state.py:_detect_project:checking",
                    "message": "Checking repositories",
                    "data": {
                        "workspace_uri": workspace_uri,
                        "workspace_path": str(workspace_path),
                        "repo_names": list(repositories.keys()),
                    },
                    "timestamp": __import__("time").time() * 1000,
                    "sessionId": "debug-session",
                    "hypothesisId": "B",
                }
            )
            + "\n"
        )
        # #endregion
        for project_name, project_config in repositories.items():
            project_path_str = project_config.get("path", "")
            if not project_path_str:
                continue

            try:
                project_path = Path(project_path_str).expanduser().resolve()
                # #region agent log
                import json as _debug_json  # noqa: F811

                open("/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log", "a").write(
                    _debug_json.dumps(
                        {
                            "location": "workspace_state.py:_detect_project:compare",
                            "message": "Comparing paths",
                            "data": {
                                "project_name": project_name,
                                "project_path": str(project_path),
                                "workspace_path": str(workspace_path),
                            },
                            "timestamp": __import__("time").time() * 1000,
                            "sessionId": "debug-session",
                            "hypothesisId": "B",
                        }
                    )
                    + "\n"
                )
                # #endregion
                # Check if workspace is the project path or a subdirectory
                workspace_path.relative_to(project_path)
                return project_name
            except ValueError:
                continue
            except Exception:
                continue

        return None

    @classmethod
    def _try_restore_workspace_from_disk(cls, workspace_uri: str) -> bool:
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
            with open(PERSIST_FILE) as f:
                data = json.load(f)

            version = data.get("version", 1)
            if version < 2:
                return False

            workspaces_data = data.get("workspaces", {})

            # Check if this workspace exists in persisted data
            if workspace_uri not in workspaces_data:
                # Also try normalized versions of the URI
                normalized_uri = workspace_uri.rstrip("/")
                for persisted_uri in workspaces_data.keys():
                    if persisted_uri.rstrip("/") == normalized_uri:
                        workspace_uri = persisted_uri
                        break
                else:
                    return False

            ws_data = workspaces_data[workspace_uri]

            # Create workspace state
            workspace = WorkspaceState(workspace_uri=workspace_uri)
            workspace.project = ws_data.get("project")
            workspace.is_auto_detected = ws_data.get("is_auto_detected", False)
            workspace.active_session_id = ws_data.get("active_session_id")

            # Parse timestamps
            if ws_data.get("created_at"):
                try:
                    workspace.created_at = datetime.fromisoformat(ws_data["created_at"])
                except (ValueError, TypeError):
                    pass

            if ws_data.get("last_activity"):
                try:
                    workspace.last_activity = datetime.fromisoformat(ws_data["last_activity"])
                except (ValueError, TypeError):
                    pass

            # Restore sessions
            sessions_data = ws_data.get("sessions", {})
            for session_id, sess_data in sessions_data.items():
                # Get session's project - use persisted value or fall back to workspace project
                session_project = sess_data.get("project")
                session_auto_detected = sess_data.get("is_project_auto_detected", False)

                # If session has no project, inherit from workspace (for backward compat)
                if session_project is None:
                    session_project = workspace.project
                    session_auto_detected = workspace.is_auto_detected

                session = ChatSession(
                    session_id=session_id,
                    workspace_uri=workspace_uri,
                    persona=sess_data.get("persona", "developer"),
                    project=session_project,
                    is_project_auto_detected=session_auto_detected,
                    issue_key=sess_data.get("issue_key"),
                    branch=sess_data.get("branch"),
                    name=sess_data.get("name"),
                )

                # Parse session timestamps
                if sess_data.get("started_at"):
                    try:
                        session.started_at = datetime.fromisoformat(sess_data["started_at"])
                    except (ValueError, TypeError):
                        pass

                if sess_data.get("last_activity"):
                    try:
                        session.last_activity = datetime.fromisoformat(sess_data["last_activity"])
                    except (ValueError, TypeError):
                        pass

                # Restore tool count (new format) or derive from active_tools (old format)
                if sess_data.get("tool_count"):
                    session.tool_count = sess_data["tool_count"]
                elif sess_data.get("active_tools"):
                    session.tool_count = len(sess_data["active_tools"])

                # Restore activity tracking
                session.last_tool = sess_data.get("last_tool")
                if sess_data.get("last_tool_time"):
                    try:
                        session.last_tool_time = datetime.fromisoformat(sess_data["last_tool_time"])
                    except (ValueError, TypeError):
                        pass
                session.tool_call_count = sess_data.get("tool_call_count", 0)

                workspace.sessions[session_id] = session

            # Add to registry
            cls._workspaces[workspace_uri] = workspace
            logger.info(f"Restored workspace {workspace_uri} with {len(workspace.sessions)} session(s) from disk")
            return True

        except Exception as e:
            logger.warning(f"Failed to restore workspace {workspace_uri} from disk: {e}")
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
            detected_project = cls._detect_project(workspace_uri)
            if detected_project:
                state.project = detected_project
                state.is_auto_detected = True
            cls._workspaces[workspace_uri] = state

        workspace = cls._workspaces[workspace_uri]

        # Auto-create session if none exists and ensure_session is True
        if ensure_session and not workspace.get_active_session():
            logger.info(f"No active session in workspace {workspace_uri}, auto-creating one")
            session = workspace.create_session(persona="developer", name="Auto-created")
            logger.info(f"Auto-created session {session.session_id} for workspace {workspace_uri}")

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
        for _workspace_uri, workspace in cls._workspaces.items():
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
    def sync_all_session_names(cls) -> int:
        """Sync session names from Cursor's database for all workspaces.

        This should be called before exporting workspace state to ensure
        session names are up-to-date with Cursor's database.

        Returns:
            Total number of sessions updated
        """
        total_updated = 0
        for workspace in cls._workspaces.values():
            total_updated += workspace.sync_session_names_from_cursor()

        if total_updated > 0:
            logger.info(f"Synced {total_updated} session name(s) from Cursor DB")
            # Persist changes to disk
            cls.save_to_disk()

        return total_updated

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
            logger.debug(f"Removed workspace state for {workspace_uri}")
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
            logger.info(f"Cleaned up stale workspace: {uri}")

        if stale_uris:
            logger.info(f"Cleaned up {len(stale_uris)} stale workspace(s)")

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

            # Build serializable state
            all_workspaces = cls.get_all_as_dict()
            all_sessions = cls.get_all_sessions()

            # Log what we're saving
            total_sessions = sum(len(ws.get("sessions", {})) for ws in all_workspaces.values())
            logger.info(f"save_to_disk: saving {len(all_workspaces)} workspace(s) with {total_sessions} session(s)")
            for uri, ws in all_workspaces.items():
                session_ids = list(ws.get("sessions", {}).keys())
                logger.info(f"  - {uri}: {len(session_ids)} sessions: {session_ids}")

            export_data = {
                "version": 2,
                "saved_at": datetime.now().isoformat(),
                "workspaces": all_workspaces,
                "sessions": all_sessions,
            }

            with open(PERSIST_FILE, "w") as f:
                json.dump(export_data, f, indent=2, default=str)

            logger.info(f"save_to_disk: successfully saved to {PERSIST_FILE}")
            return True
        except Exception as e:
            logger.error(f"Failed to save workspace state: {e}")
            return False

    @classmethod
    def load_from_disk(cls) -> int:
        """Restore workspace states from disk.

        Called on server startup to restore sessions from previous run.

        Returns:
            Number of sessions restored.
        """
        if not PERSIST_FILE.exists():
            logger.info("load_from_disk: No persisted workspace state found")
            # #region agent log
            import json as _debug_json  # noqa: F811

            open("/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log", "a").write(
                _debug_json.dumps(
                    {
                        "location": "workspace_state.py:load_from_disk:no_file",
                        "message": "No persist file found",
                        "data": {"persist_file": str(PERSIST_FILE)},
                        "timestamp": __import__("time").time() * 1000,
                        "sessionId": "debug-session",
                        "hypothesisId": "E",
                    }
                )
                + "\n"
            )
            # #endregion
            return 0

        logger.info(f"load_from_disk: Loading from {PERSIST_FILE}")
        # #region agent log
        import json as _debug_json  # noqa: F811

        open("/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log", "a").write(
            _debug_json.dumps(
                {
                    "location": "workspace_state.py:load_from_disk:loading",
                    "message": "Loading from disk",
                    "data": {"persist_file": str(PERSIST_FILE)},
                    "timestamp": __import__("time").time() * 1000,
                    "sessionId": "debug-session",
                    "hypothesisId": "E",
                }
            )
            + "\n"
        )
        # #endregion

        try:
            with open(PERSIST_FILE) as f:
                data = json.load(f)

            logger.info(f"load_from_disk: File contains {len(data.get('workspaces', {}))} workspace(s)")

            version = data.get("version", 1)
            if version < 2:
                logger.warning(f"Old persist format version {version}, skipping restore")
                return 0

            workspaces_data = data.get("workspaces", {})
            restored_sessions = 0

            for workspace_uri, ws_data in workspaces_data.items():
                # Create workspace state
                workspace = WorkspaceState(workspace_uri=workspace_uri)
                persisted_project = ws_data.get("project")
                workspace.is_auto_detected = ws_data.get("is_auto_detected", False)
                workspace.active_session_id = ws_data.get("active_session_id")

                # FIX: Re-detect project from workspace URI to ensure it matches
                # This handles the case where the persisted project is stale/incorrect
                detected_project = cls._detect_project(workspace_uri)
                if detected_project:
                    # Use detected project - it matches the workspace URI
                    workspace.project = detected_project
                    workspace.is_auto_detected = True
                    if detected_project != persisted_project:
                        logger.info(
                            f"Re-detected project '{detected_project}' for workspace "
                            f"{workspace_uri} (was '{persisted_project}')"
                        )
                else:
                    # No project detected from URI, use persisted value
                    workspace.project = persisted_project

                # #region agent log
                open("/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log", "a").write(
                    json.dumps(
                        {
                            "location": "workspace_state.py:load_from_disk:restore_workspace",
                            "message": "Restoring workspace from disk",
                            "data": {
                                "workspace_uri": workspace_uri,
                                "persisted_project": persisted_project,
                                "detected_project": detected_project,
                                "final_project": workspace.project,
                                "is_auto_detected": workspace.is_auto_detected,
                                "active_session_id": workspace.active_session_id,
                            },
                            "timestamp": __import__("time").time() * 1000,
                            "sessionId": "debug-session",
                            "hypothesisId": "E",
                        }
                    )
                    + "\n"
                )
                # #endregion

                # Parse timestamps
                if ws_data.get("created_at"):
                    try:
                        workspace.created_at = datetime.fromisoformat(ws_data["created_at"])
                    except (ValueError, TypeError):
                        pass

                if ws_data.get("last_activity"):
                    try:
                        workspace.last_activity = datetime.fromisoformat(ws_data["last_activity"])
                    except (ValueError, TypeError):
                        pass

            # Restore sessions
            sessions_data = ws_data.get("sessions", {})
            for session_id, sess_data in sessions_data.items():
                # Get session's project - use persisted value or fall back to workspace project
                session_project = sess_data.get("project")
                session_auto_detected = sess_data.get("is_project_auto_detected", False)

                # If session has no project, inherit from workspace (for backward compat)
                if session_project is None:
                    session_project = workspace.project
                    session_auto_detected = workspace.is_auto_detected

                session = ChatSession(
                    session_id=session_id,
                    workspace_uri=workspace_uri,
                    persona=sess_data.get("persona", "developer"),
                    project=session_project,
                    is_project_auto_detected=session_auto_detected,
                    issue_key=sess_data.get("issue_key"),
                    branch=sess_data.get("branch"),
                    name=sess_data.get("name"),
                )

                # Parse session timestamps
                if sess_data.get("started_at"):
                    try:
                        session.started_at = datetime.fromisoformat(sess_data["started_at"])
                    except (ValueError, TypeError):
                        # Keep the default (datetime.now()) if parsing fails
                        pass

                if sess_data.get("last_activity"):
                    try:
                        session.last_activity = datetime.fromisoformat(sess_data["last_activity"])
                    except (ValueError, TypeError):
                        pass

                # Restore tool count (new format) or derive from active_tools (old format)
                if sess_data.get("tool_count"):
                    session.tool_count = sess_data["tool_count"]
                elif sess_data.get("active_tools"):
                    session.tool_count = len(sess_data["active_tools"])

                # Restore activity tracking
                session.last_tool = sess_data.get("last_tool")
                if sess_data.get("last_tool_time"):
                    try:
                        session.last_tool_time = datetime.fromisoformat(sess_data["last_tool_time"])
                    except (ValueError, TypeError):
                        pass
                session.tool_call_count = sess_data.get("tool_call_count", 0)

                workspace.sessions[session_id] = session
                restored_sessions += 1

            # Update session names from Cursor's database (sync names if changed)
            cursor_chats = list_cursor_chats(workspace_uri)
            cursor_chat_map = {c["composerId"]: c for c in cursor_chats}
            for session_id, session in workspace.sessions.items():
                if session_id in cursor_chat_map:
                    cursor_name = cursor_chat_map[session_id].get("name")
                    if cursor_name and cursor_name != session.name:
                        logger.info(f"Updating session {session_id} name from '{session.name}' to '{cursor_name}'")
                        session.name = cursor_name

            # Only add workspace if it has sessions or is recent
            if workspace.sessions or not workspace.is_stale(max_age_hours=24):
                cls._workspaces[workspace_uri] = workspace

            logger.info(f"Restored {restored_sessions} session(s) from {len(cls._workspaces)} workspace(s)")
            return restored_sessions

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in persist file: {e}")
            return 0
        except Exception as e:
            logger.error(f"Failed to load workspace state: {e}")
            import traceback

            logger.error(traceback.format_exc())
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
                f"restore_if_empty: Registry already has {len(cls._workspaces)} workspace(s) "
                f"with {total_sessions} session(s), skipping restore"
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
