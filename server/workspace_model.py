"""WorkspaceState: a Cursor workspace (folder) and its chat sessions."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from server import cursor_chat_db, persona_loader, workspace_defaults, workspace_sync
from server.chat_session import ChatSession
from server.cursor_chat_db import CURSOR_DB_ERRORS
from server.workspace_defaults import SESSION_STALE_HOURS, as_aware, now

logger = logging.getLogger(__name__)


def _no_persist() -> None:
    """Default persistence hook (replaced by the registry)."""


@dataclass
class _PersistHook:
    """How session changes are saved (WorkspaceRegistry.save_to_disk once the registry is set up)."""

    save: Callable[[], Any] = _no_persist


_PERSIST = _PersistHook()


def set_persist_hook(save: Callable[[], Any]) -> None:
    """Register the function that persists all workspaces after a session change."""
    _PERSIST.save = save


def _generate_session_id() -> str:
    """Generate a unique session ID (fallback only)."""
    return str(uuid.uuid4())


def loaded_tool_names() -> set[str]:
    """Get currently loaded tool names from PersonaLoader."""
    try:
        loader = persona_loader.get_loader()
        if loader:
            status = loader.get_status()
            tools = set(status["tools"])
            logger.info(
                "get_loaded_tools: found %s tools from %s modules",
                len(tools),
                len(status["loaded_modules"]),
            )
            return tools
        logger.warning("get_loaded_tools: PersonaLoader not initialized")
    # Best-effort: log and continue.
    except CURSOR_DB_ERRORS as e:
        logger.warning("Could not get loaded tools: %s", e)

    return set()


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
    created_at: datetime = field(default_factory=now)
    last_activity: datetime = field(default_factory=now)

    # Metadata
    is_auto_detected: bool = False  # True if project was auto-detected from path

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = now()

    def is_stale(self, max_age_hours: int = 24) -> bool:
        """Check if workspace is stale (no activity for max_age_hours).

        Args:
            max_age_hours: Maximum hours of inactivity before considered stale

        Returns:
            True if workspace is stale
        """
        age = now() - as_aware(self.last_activity)
        return age.total_seconds() > (max_age_hours * 3600)

    def _resolve_session_id(self, session_id: str | None) -> tuple[str, str | None]:
        """Session ID to use (Cursor's chat UUID when available) and Cursor's chat name."""
        if session_id is not None:
            return session_id, None
        cursor_chat_id, cursor_chat_name = cursor_chat_db.get_cursor_chat_info_from_db(self.workspace_uri)
        if cursor_chat_id:
            logger.info("Using Cursor chat ID as session ID: %s (%s)", cursor_chat_id, cursor_chat_name)
            return cursor_chat_id, cursor_chat_name
        session_id = _generate_session_id()
        logger.info("Generated fallback session ID: %s", session_id)
        return session_id, cursor_chat_name

    def create_session(
        self,
        persona: str | None = None,
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
        session_id, cursor_chat_name = self._resolve_session_id(session_id)

        # Use workspace project as default if no project specified
        session_project = project if project is not None else self.project
        session = ChatSession(
            session_id=session_id,
            workspace_uri=self.workspace_uri,
            persona=persona if persona is not None else workspace_defaults.get_default_persona(),
            project=session_project,
            is_project_auto_detected=is_project_auto_detected if project is not None else self.is_auto_detected,
            static_tool_count=len(loaded_tool_names()),
            name=name if name is not None or not cursor_chat_name else cursor_chat_name,
        )

        self.sessions[session_id] = session
        self.active_session_id = session_id
        self.touch()

        logger.info(
            "Created session %s in workspace %s with project '%s'",
            session_id,
            self.workspace_uri,
            session_project,
        )

        # Persist to disk after creating session
        _PERSIST.save()

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
            # Refresh static tool count if zero (e.g., after restore from disk)
            if session and refresh_tools and session.static_tool_count == 0:
                session.static_tool_count = len(loaded_tool_names())
            return session
        return None

    def get_or_create_session(self, persona: str | None = None) -> ChatSession:
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
        if session_id not in self.sessions:
            return False

        del self.sessions[session_id]
        if self.active_session_id == session_id:
            # Set active to most recent remaining session
            if self.sessions:
                most_recent = max(self.sessions.values(), key=lambda s: as_aware(s.last_activity))
                self.active_session_id = most_recent.session_id
            else:
                self.active_session_id = None
        logger.info("Removed session %s from workspace %s", session_id, self.workspace_uri)

        # Persist to disk after removing session
        _PERSIST.save()
        return True

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
        cursor_chat_ids = cursor_chat_db.get_cursor_chat_ids(self.workspace_uri)

        # Only remove sessions that are stale AND not in Cursor's database
        stale_ids = [
            sid
            for sid, session in self.sessions.items()
            if session.is_stale(max_age_hours) and sid not in cursor_chat_ids
        ]

        for sid in stale_ids:
            self.remove_session(sid)

        if stale_ids:
            logger.info(
                "Cleaned up %s stale session(s) not in Cursor DB from %s",
                len(stale_ids),
                self.workspace_uri,
            )

        return len(stale_ids)

    def session_count(self) -> int:
        """Get number of sessions in this workspace."""
        return len(self.sessions)

    def _sync_inputs(self, cursor_chats: list[dict], scan_ids: list[str]) -> workspace_sync.SyncInputs:
        """Collect Cursor's chats, content scan results and the loaded tool count."""
        chat_map = {c["composerId"]: c for c in cursor_chats}
        current_tool_count = len(loaded_tool_names())
        scan = workspace_sync.scan_content(scan_ids)
        return workspace_sync.SyncInputs(
            chat_map=chat_map,
            issue_keys=workspace_sync.merge_issue_keys(chat_map, scan.issue_keys),
            scan=scan,
            current_tool_count=current_tool_count,
        )

    def _remove_missing_sessions(self, removed_ids: set[str]) -> None:
        """Drop sessions whose chats no longer exist in Cursor."""
        for sid in removed_ids:
            logger.info("Removing session %s - no longer in Cursor DB", sid)
            del self.sessions[sid]
            if self.active_session_id == sid:
                self.active_session_id = None

    def sync_with_cursor_db(self, session_ids: list[str] | None = None, skip_content_scan: bool = False) -> dict:
        """Sync with Cursor's database.

        This keeps our sessions in sync with Cursor:
        - Adds sessions that exist in Cursor but not in our system
        - Removes sessions that no longer exist in Cursor (archived/deleted)
        - Updates names when Cursor's name changes
        - Updates last_activity from Cursor's lastUpdatedAt
        - Updates tool_count based on persona
        - Scans chat content for Jira issue keys (AAP-XXXXX)

        Args:
            session_ids: Optional list of session IDs to sync. If provided, only
                        these sessions will have their content scanned (expensive).
                        Session adds/removes still happen for all sessions.
            skip_content_scan: If True, skip all expensive content scanning.
                              Useful for initial sync to get basic state quickly.

        Returns:
            Dict with counts: {"added": N, "removed": N, "renamed": N, "updated": N}
        """
        cursor_chats, cursor_active_id = cursor_chat_db.list_cursor_chats(self.workspace_uri)
        cursor_ids = {c["composerId"] for c in cursor_chats}
        our_ids = set(self.sessions.keys())

        # Update active session from Cursor's lastFocusedComposerIds
        if cursor_active_id and cursor_active_id in cursor_ids and self.active_session_id != cursor_active_id:
            logger.info("Updating active session from Cursor: %s", cursor_active_id)
            self.active_session_id = cursor_active_id

        # Content scanning is expensive: only for the given sessions, never by default
        scan_ids = list(session_ids) if session_ids and not skip_content_scan else []
        inputs = self._sync_inputs(cursor_chats, scan_ids)

        removed_ids = our_ids - cursor_ids
        self._remove_missing_sessions(removed_ids)

        # Chats the user created but never called session_start() for
        added_ids = cursor_ids - our_ids
        for sid in added_ids:
            self.sessions[sid] = workspace_sync.session_from_cursor_chat(self, sid, inputs)

        result = {"added": len(added_ids), "removed": len(removed_ids), "renamed": 0, "updated": 0}
        for sid in our_ids & cursor_ids:
            session = self.sessions[sid]
            if workspace_sync.sync_name(session, inputs.chat_map[sid]):
                result["renamed"] += 1
            if workspace_sync.update_existing_session(session, sid == self.active_session_id, inputs):
                result["updated"] += 1

        workspace_sync.refresh_meeting_references(list(self.sessions.values()))

        if sum(result.values()) > 0:
            logger.info(
                "Synced with Cursor DB for %s: +%s -%s ~%s ↻%s",
                self.workspace_uri,
                result["added"],
                result["removed"],
                result["renamed"],
                result["updated"],
            )

        return result

    # Keep old name as alias for backward compatibility
    def sync_session_names_from_cursor(self) -> int:
        """Deprecated: Use sync_with_cursor_db() instead."""
        result = self.sync_with_cursor_db()
        return result["renamed"]

    def _get_loaded_tools(self) -> set[str]:
        """Currently loaded tool names (kept for existing callers; see :func:`loaded_tool_names`)."""
        return loaded_tool_names()

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
        return session.persona if session else workspace_defaults.get_default_persona()

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
