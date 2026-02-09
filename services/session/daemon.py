#!/usr/bin/env python3
"""
Session Daemon - Cursor Session State Manager

A standalone service that manages Cursor session state with real-time updates.
Designed to run as a systemd user service.

Features:
- Watches Cursor's database for session changes
- D-Bus IPC for external control and queries
- Full-text search of chat content
- Real-time state change notifications
- Periodic sync with workspace_states.json
- Systemd watchdog support

Usage:
    python -m services.session                # Run daemon
    python -m services.session --status       # Check if running
    python -m services.session --stop         # Stop running daemon
    python -m services.session --search "query"  # Search chats
    python -m services.session --dbus         # Enable D-Bus IPC

Systemd:
    systemctl --user start bot-session
    systemctl --user status bot-session
    systemctl --user stop bot-session

D-Bus:
    Service: com.aiworkflow.BotSession
    Path: /com/aiworkflow/BotSession

    Methods:
    - GetSessions() -> JSON list of sessions
    - SearchChats(query: str, limit: int) -> JSON search results
    - RefreshNow() -> Trigger immediate sync
    - GetState() -> Full workspace state JSON

    Signals:
    - StateChanged(change_type: str) - Emitted when sessions change
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

# Import centralized paths
from server.paths import CURSOR_WORKSPACE_STORAGE, SESSION_STATE_FILE
from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase
from services.base.sleep_wake import SleepWakeAwareDaemon

logger = logging.getLogger(__name__)


class SessionDaemon(SleepWakeAwareDaemon, DaemonDBusBase, BaseDaemon):
    """Main session daemon with D-Bus and sleep/wake support."""

    # BaseDaemon configuration
    name = "session"
    description = "Session Daemon - Cursor session state manager"

    # D-Bus configuration
    service_name = "com.aiworkflow.BotSession"
    object_path = "/com/aiworkflow/BotSession"
    interface_name = "com.aiworkflow.BotSession"

    def __init__(self, verbose: bool = False, enable_dbus: bool = True):
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)
        SleepWakeAwareDaemon.__init__(self)

        # State tracking
        self._last_state_hash: str = ""
        self._sync_count: int = 0
        self._last_sync_time: float = 0
        self._search_count: int = 0
        self._configured_paths: set[str] = set()

        # Tiered sync intervals (seconds)
        # Fast: Active session detection only (lightweight)
        self._fast_sync_interval: float = 2.0
        # Recent: Full sync for last N active sessions
        self._recent_sync_interval: float = 10.0
        self._recent_session_count: int = 5
        # Background: Incremental sync for all other sessions
        self._background_sync_interval: float = 120.0
        self._background_batch_size: int = 10  # Sessions per batch

        # Legacy intervals (for backward compat)
        self._sync_interval: float = self._background_sync_interval
        self._watch_interval: float = self._fast_sync_interval

        # Track recent active sessions for prioritized sync
        self._recent_active_sessions: list[str] = []  # Ordered by recency
        self._last_active_session_id: str | None = None

        # Track session count for detecting deletions
        self._last_session_count: int = -1  # -1 means not yet initialized

        # Track DB modification times to skip unchanged workspaces
        self._db_mtimes: dict[str, float] = {}  # path -> mtime

        # Background sync state (for incremental processing)
        self._background_sync_offset: int = 0
        self._last_background_sync: float = 0

        # Register custom D-Bus method handlers
        self.register_handler("search_chats", self._handle_search_chats)
        self.register_handler("get_sessions", self._handle_get_sessions)
        self.register_handler("refresh_now", self._handle_refresh_now)
        self.register_handler("get_state", self._handle_get_state)
        self.register_handler("write_state", self._handle_write_state)
        self.register_handler("remove_workspace", self._handle_remove_workspace)

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return session-specific statistics."""
        return {
            "sync_count": self._sync_count,
            "last_sync_time": self._last_sync_time,
            "search_count": self._search_count,
            "configured_workspaces": len(self._configured_paths),
            "sync_interval": self._sync_interval,
            "fast_sync_interval": self._fast_sync_interval,
            "recent_sync_interval": self._recent_sync_interval,
            "background_sync_interval": self._background_sync_interval,
            "recent_active_sessions": len(self._recent_active_sessions),
            "last_active_session": self._last_active_session_id,
        }

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        base = self.get_base_stats()
        service = await self.get_service_stats()

        # Add current session count
        try:
            if SESSION_STATE_FILE.exists():
                data = json.loads(SESSION_STATE_FILE.read_text())
                service["session_count"] = data.get("session_count", 0)
                service["workspace_count"] = data.get("workspace_count", 0)
        except Exception:
            service["session_count"] = 0
            service["workspace_count"] = 0

        return {**base, **service}

    async def health_check(self) -> dict:
        """Perform a health check on the session daemon."""
        now = time.time()
        self._last_health_check = now

        checks = {
            "running": self.is_running,
            "config_loaded": len(self._configured_paths) > 0,
        }

        # Check if we've synced recently (informational, not required for health)
        if self._last_sync_time > 0:
            time_since_sync = now - self._last_sync_time
            checks["recent_sync"] = time_since_sync < (self._sync_interval * 3)
        else:
            checks["recent_sync"] = False

        # Check uptime (informational, not required for health)
        if self.start_time:
            checks["uptime_ok"] = (now - self.start_time) > 5
        else:
            checks["uptime_ok"] = False

        # Only core checks required for health - uptime_ok and recent_sync are informational
        core_checks = ["running", "config_loaded"]
        healthy = all(checks.get(k, False) for k in core_checks)
        message = (
            "Session daemon is healthy"
            if healthy
            else f"Unhealthy: {[k for k in core_checks if not checks.get(k, False)]}"
        )

        return {
            "healthy": healthy,
            "checks": checks,
            "message": message,
            "timestamp": now,
            "sync_count": self._sync_count,
        }

    # ==================== D-Bus Method Handlers ====================

    async def _handle_search_chats(self, query: str, limit: int = 20) -> dict:
        """Search chat content across all configured workspaces."""
        self._search_count += 1
        results = []

        try:
            workspace_storage = CURSOR_WORKSPACE_STORAGE
            if not workspace_storage.exists():
                return {
                    "results": [],
                    "query": query,
                    "error": "Cursor storage not found",
                }

            query_lower = query.lower()
            query_pattern = re.compile(re.escape(query), re.IGNORECASE)

            for storage_dir in workspace_storage.iterdir():
                if not storage_dir.is_dir():
                    continue

                workspace_json = storage_dir / "workspace.json"
                if not workspace_json.exists():
                    continue

                try:
                    workspace_data = json.loads(workspace_json.read_text())
                    folder_uri = workspace_data.get("folder", "")

                    # Convert to path and check if configured
                    if folder_uri.startswith("file://"):
                        workspace_path = folder_uri[7:]
                    else:
                        workspace_path = folder_uri

                    workspace_path_resolved = str(Path(workspace_path).resolve())
                    if workspace_path_resolved not in self._configured_paths:
                        continue

                    # Query the database
                    db_path = storage_dir / "state.vscdb"
                    if not db_path.exists():
                        continue

                    # Use context manager to ensure connection is always closed
                    with sqlite3.connect(str(db_path)) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT value FROM ItemTable WHERE key = 'composer.composerData'"
                        )
                        row = cursor.fetchone()

                    if not row or not row[0]:
                        continue

                    composer_data = json.loads(row[0])
                    all_composers = composer_data.get("allComposers", [])

                    for composer in all_composers:
                        if composer.get("isArchived") or composer.get("isDraft"):
                            continue

                        composer_id = composer.get("composerId", "")
                        name = composer.get("name", "")
                        conversation = composer.get("conversation", [])

                        # Search in name
                        name_match = query_lower in (name or "").lower()

                        # Search in conversation content
                        content_matches = []
                        for msg in conversation:
                            text = msg.get("text", "") or msg.get("content", "")
                            if not text or query_lower not in text.lower():
                                continue
                            match = query_pattern.search(text)
                            if not match:
                                continue
                            start = max(0, match.start() - 50)
                            end = min(len(text), match.end() + 50)
                            snippet = text[start:end]
                            if start > 0:
                                snippet = "..." + snippet
                            if end < len(text):
                                snippet = snippet + "..."
                            content_matches.append(
                                {
                                    "snippet": snippet,
                                    "role": msg.get("role", "unknown"),
                                }
                            )

                        if name_match or content_matches:
                            # Get project name from workspace path
                            project = workspace_path.split("/")[-1]

                            results.append(
                                {
                                    "session_id": composer_id,
                                    "name": name or f"Session {composer_id[:8]}",
                                    "project": project,
                                    "workspace_uri": folder_uri,
                                    "name_match": name_match,
                                    "content_matches": content_matches[
                                        :3
                                    ],  # Limit snippets
                                    "match_count": len(content_matches),
                                    "last_updated": composer.get("lastUpdatedAt"),
                                }
                            )

                            if len(results) >= limit:
                                break

                except (json.JSONDecodeError, sqlite3.Error) as e:
                    logger.debug(f"Error searching {storage_dir}: {e}")
                    continue

                if len(results) >= limit:
                    break

            # Sort by relevance (name matches first, then by match count)
            results.sort(key=lambda x: (not x["name_match"], -x["match_count"]))

            return {
                "results": results[:limit],
                "query": query,
                "total_found": len(results),
            }

        except Exception as e:
            logger.error(f"Search error: {e}")
            return {"results": [], "query": query, "error": str(e)}

    async def _handle_get_sessions(self) -> dict:
        """Get all sessions from session state."""
        try:
            if SESSION_STATE_FILE.exists():
                data = json.loads(SESSION_STATE_FILE.read_text())
                return {
                    "sessions": data.get("sessions", []),
                    "session_count": data.get("session_count", 0),
                    "updated_at": data.get("updated_at"),
                }
            return {"sessions": [], "session_count": 0}
        except Exception as e:
            return {"sessions": [], "error": str(e)}

    async def _handle_refresh_now(self) -> dict:
        """Trigger immediate sync."""
        try:
            await self._do_sync()
            return {"success": True, "sync_count": self._sync_count}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_get_state(self) -> dict:
        """Get full session state."""
        try:
            if SESSION_STATE_FILE.exists():
                return json.loads(SESSION_STATE_FILE.read_text())
            return {}
        except Exception as e:
            return {"error": str(e)}

    async def _handle_write_state(self) -> dict:
        """Write state to file immediately (for UI refresh requests)."""
        try:
            await self._do_sync()
            return {"success": True, "file": str(SESSION_STATE_FILE)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_remove_workspace(self, uri: str = None, **kwargs) -> dict:
        """Remove a workspace from tracking.

        Args:
            uri: The workspace URI to remove

        Returns:
            dict with success status
        """
        if not uri:
            return {"success": False, "error": "uri required"}

        try:
            from server.workspace_state import WorkspaceRegistry

            # Load current state
            WorkspaceRegistry.load_from_disk()

            # Check if workspace exists
            if uri not in WorkspaceRegistry._workspaces:
                return {"success": False, "error": f"Workspace {uri} not found"}

            # Remove the workspace
            del WorkspaceRegistry._workspaces[uri]

            # Save to disk
            WorkspaceRegistry.save_to_disk()

            # Update our state file
            await self._do_sync()

            logger.info(f"Removed workspace: {uri}")
            return {"success": True, "message": f"Removed workspace: {uri}"}

        except Exception as e:
            logger.error(f"Failed to remove workspace {uri}: {e}")
            return {"success": False, "error": str(e)}

    # ==================== Core Logic ====================

    def _load_configured_paths(self):
        """Load configured repository paths from config.json."""
        try:
            from server.config_manager import config as config_manager

            repos = config_manager.get("repositories", default={})
            self._configured_paths = set()
            for repo in repos.values():
                local_path = repo.get("path", "")
                if local_path:
                    self._configured_paths.add(str(Path(local_path).resolve()))
            logger.info(
                f"Loaded {len(self._configured_paths)} configured repository paths"
            )
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self._configured_paths = set()

    def _compute_state_hash(self) -> str:
        """Compute a hash of the current Cursor session state."""
        try:
            workspace_storage = CURSOR_WORKSPACE_STORAGE
            if not workspace_storage.exists():
                return ""

            # Hash the modification times and sizes of relevant DB files
            hash_data = []
            for storage_dir in workspace_storage.iterdir():
                if not storage_dir.is_dir():
                    continue

                workspace_json = storage_dir / "workspace.json"
                if not workspace_json.exists():
                    continue

                try:
                    workspace_data = json.loads(workspace_json.read_text())
                    folder_uri = workspace_data.get("folder", "")
                    if folder_uri.startswith("file://"):
                        workspace_path = folder_uri[7:]
                    else:
                        workspace_path = folder_uri

                    workspace_path_resolved = str(Path(workspace_path).resolve())
                    if workspace_path_resolved not in self._configured_paths:
                        continue

                    db_path = storage_dir / "state.vscdb"
                    if db_path.exists():
                        stat = db_path.stat()
                        hash_data.append(f"{db_path}:{stat.st_mtime}:{stat.st_size}")
                except Exception:
                    continue

            return hashlib.md5("|".join(sorted(hash_data)).encode()).hexdigest()
        except Exception as e:
            logger.debug(f"Error computing state hash: {e}")
            return ""

    def _build_workspace_storage_map(self) -> None:
        """Build a mapping of workspace URIs to their storage directories.

        This is called once at startup and cached to avoid iterating
        106+ directories every second.
        """
        self._workspace_storage_map: dict[str, Path] = (
            {}
        )  # workspace_uri -> storage_dir
        workspace_storage = CURSOR_WORKSPACE_STORAGE

        if not workspace_storage.exists():
            return

        for storage_dir in workspace_storage.iterdir():
            if not storage_dir.is_dir():
                continue

            workspace_json = storage_dir / "workspace.json"
            if not workspace_json.exists():
                continue

            try:
                workspace_data = json.loads(workspace_json.read_text())
                folder_uri = workspace_data.get("folder", "")

                # Check if this is a configured workspace
                if folder_uri.startswith("file://"):
                    workspace_path = folder_uri[7:]
                else:
                    workspace_path = folder_uri

                workspace_path_resolved = str(Path(workspace_path).resolve())
                if workspace_path_resolved in self._configured_paths:
                    self._workspace_storage_map[folder_uri] = storage_dir

            except (json.JSONDecodeError, OSError):
                continue

        logger.info(
            f"Built workspace storage map: {len(self._workspace_storage_map)} configured workspaces"
        )

    def _get_active_session_ids(self) -> tuple[dict[str, str | None], int]:
        """Get active session IDs from Cursor's workspace databases (fast, lightweight).

        This only reads the composer metadata, not chat content.
        Uses cached workspace-to-storage mapping to avoid iterating all directories.

        Returns:
            Tuple of (Dict mapping workspace_uri to active session ID, total session count)
        """
        active_sessions: dict[str, str | None] = {}
        total_session_count = 0

        # Build map if not exists
        if (
            not hasattr(self, "_workspace_storage_map")
            or not self._workspace_storage_map
        ):
            self._build_workspace_storage_map()

        # Initialize session count cache if needed
        if not hasattr(self, "_workspace_session_counts"):
            self._workspace_session_counts: dict[str, int] = {}

        # Only check configured workspaces (5 instead of 106)
        for folder_uri, storage_dir in self._workspace_storage_map.items():
            try:
                db_path = storage_dir / "state.vscdb"
                if not db_path.exists():
                    continue

                # Check if DB has changed since last read
                stat = db_path.stat()
                cached_mtime = self._db_mtimes.get(str(db_path), 0)
                if stat.st_mtime == cached_mtime:
                    # DB unchanged, use cached session count
                    total_session_count += self._workspace_session_counts.get(
                        folder_uri, 0
                    )
                    continue

                # Use sqlite3 module directly (faster than subprocess)
                # Use context manager to ensure connection is always closed
                with sqlite3.connect(str(db_path)) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT value FROM ItemTable WHERE key = 'composer.composerData'"
                    )
                    row = cursor.fetchone()

                if row and row[0]:
                    composer_data = json.loads(row[0])
                    last_focused = composer_data.get("lastFocusedComposerIds", [])
                    if last_focused:
                        active_sessions[folder_uri] = last_focused[0]
                    else:
                        active_sessions[folder_uri] = None

                    # Count non-archived, non-draft sessions
                    all_composers = composer_data.get("allComposers", [])
                    active_count = sum(
                        1
                        for c in all_composers
                        if not c.get("isArchived") and not c.get("isDraft")
                    )
                    total_session_count += active_count

                    # Cache the session count for this workspace
                    self._workspace_session_counts[folder_uri] = active_count

                    # Update mtime cache
                    self._db_mtimes[str(db_path)] = stat.st_mtime

            except (json.JSONDecodeError, sqlite3.Error) as e:
                logger.debug(f"Error reading workspace {storage_dir}: {e}")
                continue

        return active_sessions, total_session_count

    def _update_recent_sessions(self, active_session_id: str | None) -> None:
        """Update the list of recently active sessions."""
        if not active_session_id:
            return

        # Remove if already in list
        if active_session_id in self._recent_active_sessions:
            self._recent_active_sessions.remove(active_session_id)

        # Add to front (most recent)
        self._recent_active_sessions.insert(0, active_session_id)

        # Trim to max size
        self._recent_active_sessions = self._recent_active_sessions[
            : self._recent_session_count
        ]

        # Track last active
        self._last_active_session_id = active_session_id

    async def _do_fast_sync(self) -> bool:
        """Fast sync: Only detect active session changes (1 second interval).

        This is lightweight - just reads composer metadata, not chat content.
        Also detects session count changes (deletions) and triggers full sync.

        Returns:
            True if active session changed or session count changed, False otherwise
        """
        try:
            active_sessions, session_count = self._get_active_session_ids()

            changed = False

            # Check for session count changes (sessions added or deleted)
            if (
                self._last_session_count >= 0
                and session_count != self._last_session_count
            ):
                logger.info(
                    f"Session count changed: {self._last_session_count} -> {session_count}, "
                    "triggering full sync"
                )
                # Trigger a full sync to update the registry with adds/removes
                await self._do_sync()
                changed = True

            self._last_session_count = session_count

            # Check for active session changes
            for _workspace_uri, session_id in active_sessions.items():
                if session_id and session_id != self._last_active_session_id:
                    logger.debug(
                        f"Active session changed: {session_id[:8] if session_id else 'None'}"
                    )
                    self._update_recent_sessions(session_id)
                    changed = True

            return changed

        except Exception as e:
            logger.debug(f"Fast sync error: {e}")
            return False

    async def _do_recent_sync(self) -> dict:
        """Sync recent active sessions with full detail (5 second interval).

        This syncs the last N active sessions with full chat content scanning
        for persona, issue keys, project, etc.

        Returns:
            Sync result dict
        """
        # Skip if no recent sessions to sync
        if not self._recent_active_sessions:
            logger.debug("Recent sync: No recent sessions, skipping")
            return {"added": 0, "removed": 0, "renamed": 0, "updated": 0}

        try:
            from server.workspace_state import WorkspaceRegistry

            # Note: We don't load from disk every time - the registry persists in memory
            # Only load if registry is empty (first run after startup)
            if WorkspaceRegistry.count() == 0:
                WorkspaceRegistry.load_from_disk()

            # Sync only recent sessions (never pass None - that triggers full scan)
            sync_result = WorkspaceRegistry.sync_sessions_with_cursor(
                session_ids=self._recent_active_sessions
            )

            # Get all workspace states and sessions for state file
            all_states = WorkspaceRegistry.get_all_as_dict()
            all_sessions = WorkspaceRegistry.get_all_sessions()

            # Build session state
            session_state = {
                "workspaces": all_states,
                "sessions": all_sessions,
                "workspace_count": len(all_states),
                "session_count": (
                    len(all_sessions)
                    if all_sessions
                    else sum(len(ws.get("sessions", {})) for ws in all_states.values())
                ),
                "last_sync": sync_result,
                "sync_type": "recent",
                "recent_sessions": self._recent_active_sessions,
                "updated_at": datetime.now().isoformat(),
            }

            # Write state file
            self._write_state_file(session_state)

            self._sync_count += 1
            self._last_sync_time = time.time()
            logger.debug(
                f"Recent sync: {len(self._recent_active_sessions)} sessions, {sync_result}"
            )
            self.record_successful_operation()

            return sync_result

        except Exception as e:
            logger.error(f"Recent sync error: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            self.record_failed_operation()
            return {"error": str(e)}

    async def _do_background_sync(self) -> dict:
        """Background sync: Incremental sync for all other sessions (60 second interval).

        Processes sessions in batches to avoid CPU spikes.

        Returns:
            Sync result dict
        """
        try:
            from server.workspace_state import WorkspaceRegistry

            # Only load if registry is empty
            if WorkspaceRegistry.count() == 0:
                WorkspaceRegistry.load_from_disk()

            # Get all session IDs
            all_sessions = WorkspaceRegistry.get_all_sessions()
            all_session_ids = [
                s.get("session_id") for s in all_sessions if s.get("session_id")
            ]

            # Exclude recent sessions (already synced frequently)
            background_ids = [
                sid
                for sid in all_session_ids
                if sid not in self._recent_active_sessions
            ]

            if not background_ids:
                logger.debug("No background sessions to sync")
                return {"added": 0, "removed": 0, "renamed": 0, "updated": 0}

            # Get batch for this cycle
            batch_start = self._background_sync_offset
            batch_end = batch_start + self._background_batch_size
            batch_ids = background_ids[batch_start:batch_end]

            # Update offset for next cycle (wrap around)
            if batch_end >= len(background_ids):
                self._background_sync_offset = 0
            else:
                self._background_sync_offset = batch_end

            if not batch_ids:
                return {"added": 0, "removed": 0, "renamed": 0, "updated": 0}

            logger.debug(
                f"Background sync batch: {len(batch_ids)} sessions (offset {batch_start})"
            )

            # Sync this batch
            sync_result = WorkspaceRegistry.sync_sessions_with_cursor(
                session_ids=batch_ids
            )

            # Get updated states
            all_states = WorkspaceRegistry.get_all_as_dict()
            all_sessions = WorkspaceRegistry.get_all_sessions()

            # Build session state
            session_state = {
                "workspaces": all_states,
                "sessions": all_sessions,
                "workspace_count": len(all_states),
                "session_count": len(all_sessions),
                "last_sync": sync_result,
                "sync_type": "background",
                "batch_offset": batch_start,
                "batch_size": len(batch_ids),
                "total_background": len(background_ids),
                "updated_at": datetime.now().isoformat(),
            }

            # Write state file
            self._write_state_file(session_state)

            self._last_background_sync = time.time()
            logger.debug(
                f"Background sync: batch {batch_start}-{batch_end}, {sync_result}"
            )

            return sync_result

        except Exception as e:
            logger.error(f"Background sync error: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            return {"error": str(e)}

    async def _do_initial_sync(self):
        """Initial lightweight sync - skips expensive content scanning.

        Called at startup to quickly populate state. Content scanning
        happens incrementally via background sync.
        """
        try:
            from server.workspace_state import WorkspaceRegistry

            # Load from disk
            WorkspaceRegistry.load_from_disk()

            # Ensure configured workspaces exist
            for workspace_path in self._configured_paths:
                workspace_uri = workspace_path
                if not workspace_uri.startswith("file://"):
                    workspace_uri = f"file://{workspace_path}"
                WorkspaceRegistry.get_or_create(workspace_uri, ensure_session=False)

            # Lightweight sync - just names and timestamps, no content scanning
            # Pass empty list to skip content scanning entirely
            sync_result = WorkspaceRegistry.sync_all_with_cursor(skip_content_scan=True)

            # Get all workspace states
            all_states = WorkspaceRegistry.get_all_as_dict()
            all_sessions = WorkspaceRegistry.get_all_sessions()

            # Build session state
            session_state = {
                "workspaces": all_states,
                "sessions": all_sessions,
                "workspace_count": len(all_states),
                "session_count": len(all_sessions),
                "last_sync": sync_result,
                "sync_type": "initial",
                "updated_at": datetime.now().isoformat(),
            }

            # Write state file
            self._write_state_file(session_state)

            self._sync_count += 1
            self._last_sync_time = time.time()
            logger.info(f"Initial sync complete: {len(all_sessions)} sessions")
            self.record_successful_operation()

        except Exception as e:
            logger.error(f"Initial sync error: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            self.record_failed_operation()

    async def _do_sync(self):
        """Full sync - called on manual refresh.

        Each service writes to its own state file. The VS Code extension
        reads all state files on refresh and merges them for display.
        This prevents race conditions - no shared file between services.
        """
        try:
            from server.workspace_state import WorkspaceRegistry

            # Load from disk (registry is per-process, so we need to load first)
            WorkspaceRegistry.load_from_disk()

            # Ensure configured workspaces exist
            for workspace_path in self._configured_paths:
                # Convert path to file:// URI if needed
                workspace_uri = workspace_path
                if not workspace_uri.startswith("file://"):
                    workspace_uri = f"file://{workspace_path}"
                WorkspaceRegistry.get_or_create(workspace_uri, ensure_session=False)

            # Full sync with Cursor's database
            sync_result = WorkspaceRegistry.sync_all_with_cursor()

            # Get all workspace states
            all_states = WorkspaceRegistry.get_all_as_dict()
            all_sessions = WorkspaceRegistry.get_all_sessions()

            # Build session state
            session_state = {
                "workspaces": all_states,
                "sessions": all_sessions,
                "workspace_count": len(all_states),
                "session_count": (
                    len(all_sessions)
                    if all_sessions
                    else sum(len(ws.get("sessions", {})) for ws in all_states.values())
                ),
                "last_sync": sync_result,
                "sync_type": "full",
                "updated_at": datetime.now().isoformat(),
            }

            # Write to our own state file atomically
            self._write_state_file(session_state)

            self._sync_count += 1
            self._last_sync_time = time.time()
            logger.debug(f"Full sync: {len(all_sessions)} sessions, {sync_result}")
            self.record_successful_operation()

        except Exception as e:
            logger.error(f"Session sync error: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            self.record_failed_operation()

    def _write_state_file(self, state: dict) -> None:
        """Write state to session_state.json atomically."""
        import tempfile

        SESSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file then rename (atomic on POSIX)
        temp_fd, temp_path = tempfile.mkstemp(
            suffix=".tmp", prefix="session_state_", dir=SESSION_STATE_FILE.parent
        )
        try:
            with os.fdopen(temp_fd, "w") as f:
                json.dump(state, f, indent=2, default=str)
            Path(temp_path).replace(SESSION_STATE_FILE)
        except Exception:
            try:
                Path(temp_path).unlink()
            except OSError as exc:
                logger.debug("OS operation failed: %s", exc)
            raise

    async def _fast_sync_loop(self):
        """Fast sync loop: Detect active session changes (1 second interval).

        This is lightweight - just reads composer metadata to detect which
        session is currently active. Triggers recent sync when active changes.
        """
        logger.info(f"Starting fast sync loop (interval: {self._fast_sync_interval}s)")

        while not self._shutdown_event.is_set():
            try:
                # Fast check for active session changes
                changed = await self._do_fast_sync()

                if changed:
                    # Active session changed, trigger immediate recent sync
                    logger.info("Active session changed, triggering recent sync...")
                    await self._do_recent_sync()

                    # Emit D-Bus signal
                    self.emit_event(
                        "StateChanged",
                        json.dumps(
                            {
                                "type": "active_session_changed",
                                "session_id": self._last_active_session_id,
                            }
                        ),
                    )

                await asyncio.sleep(self._fast_sync_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Fast sync loop error: {e}")
                await asyncio.sleep(2)

    async def _recent_sync_loop(self):
        """Recent sync loop: Full sync for recent sessions (5 second interval).

        Syncs the last N active sessions with full detail (persona, issue keys, etc).
        """
        logger.info(
            f"Starting recent sync loop (interval: {self._recent_sync_interval}s)"
        )

        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self._recent_sync_interval)

                if self._shutdown_event.is_set():
                    break

                # Sync recent sessions
                await self._do_recent_sync()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Recent sync loop error: {e}")
                await asyncio.sleep(5)

    async def _background_sync_loop(self):
        """Background sync loop: Incremental sync for all sessions (60 second interval).

        Processes sessions in batches to avoid CPU spikes.
        """
        logger.info(
            f"Starting background sync loop (interval: {self._background_sync_interval}s)"
        )

        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self._background_sync_interval)

                if self._shutdown_event.is_set():
                    break

                # Incremental background sync
                await self._do_background_sync()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Background sync loop error: {e}")
                await asyncio.sleep(10)

    # ==================== Lifecycle ====================

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

        logger.info("Session daemon starting...")

        # Load configuration
        self._load_configured_paths()

        # Initial lightweight sync to populate state (skip expensive content scanning)
        logger.info("Running initial lightweight sync...")
        await self._do_initial_sync()
        self._last_state_hash = self._compute_state_hash()

        # Start D-Bus if enabled
        if self.enable_dbus:
            await self.start_dbus()

        self.is_running = True

        # Create tiered sync tasks
        self._fast_task = asyncio.create_task(self._fast_sync_loop())
        self._recent_task = asyncio.create_task(self._recent_sync_loop())
        self._background_task = asyncio.create_task(self._background_sync_loop())

        # Start sleep/wake monitor
        await self.start_sleep_monitor()

        logger.info(
            "Session daemon ready with tiered sync: "
            f"fast={self._fast_sync_interval}s, "
            f"recent={self._recent_sync_interval}s (top {self._recent_session_count}), "
            f"background={self._background_sync_interval}s (batch {self._background_batch_size})"
        )

    async def run_daemon(self):
        """Main daemon loop - wait for shutdown."""
        await self._shutdown_event.wait()

    async def shutdown(self):
        """Clean up daemon resources."""
        logger.info("Session daemon shutting down...")

        # Stop sleep/wake monitor
        await self.stop_sleep_monitor()

        # Cancel sync tasks
        for task in [self._fast_task, self._recent_task, self._background_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Stop D-Bus
        if self.enable_dbus:
            await self.stop_dbus()

        self.is_running = False
        await super().shutdown()
        logger.info("Session daemon stopped")

    async def on_system_wake(self):
        """Handle system wake from sleep - refresh session state."""
        logger.info("System wake detected - triggering session refresh")
        try:
            # Trigger immediate sync of recent sessions
            await self._sync_recent_sessions()
            logger.info("Post-wake session refresh complete")
        except Exception as e:
            logger.error(f"Error refreshing sessions after wake: {e}")


if __name__ == "__main__":
    SessionDaemon.main()
