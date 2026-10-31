"""Blocking session sync jobs for the session daemon (run in worker threads).

Split out of ``services/session/daemon.py``. Each job syncs
``WorkspaceRegistry`` with Cursor and writes ``session_state.json``.
"""

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from server.paths import SESSION_STATE_FILE
from server.workspace_state import WorkspaceRegistry

logger = logging.getLogger(__name__)


def now_iso() -> str:
    """Current local time, ISO 8601 with UTC offset."""
    return datetime.now().astimezone().isoformat()


EMPTY_RESULT = {"added": 0, "removed": 0, "renamed": 0, "updated": 0}


@dataclass
class SessionTracker:
    """Recently active sessions and the background batch position."""

    max_recent: int = 5
    batch_size: int = 10
    recent: list[str] = field(default_factory=list)
    last_active: str | None = None
    last_session_count: int = -1  # -1 until the first fast sync
    background_offset: int = 0
    # Serializes WorkspaceRegistry access across the fast/recent/background loops.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def mark_active(self, session_id: str | None) -> None:
        """Move *session_id* to the front of the recent list."""
        if not session_id:
            return
        if session_id in self.recent:
            self.recent.remove(session_id)
        self.recent.insert(0, session_id)
        self.recent = self.recent[: self.max_recent]
        self.last_active = session_id

    def next_batch(self, background_ids: list[str]) -> tuple[int, list[str]]:
        """Next batch of background session IDs and its offset; wraps at the end."""
        start = self.background_offset
        end = start + self.batch_size
        self.background_offset = 0 if end >= len(background_ids) else end
        return start, background_ids[start:end]


def write_state_file(state: dict, path: Path = SESSION_STATE_FILE) -> None:
    """Write *state* to *path* atomically (temp file, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(suffix=".tmp", prefix="session_state_", dir=path.parent)
    written = False
    try:
        with os.fdopen(temp_fd, "w") as f:
            json.dump(state, f, indent=2, default=str)
        Path(temp_path).replace(path)
        written = True
    finally:
        if not written:
            try:
                Path(temp_path).unlink()
            except OSError as exc:
                logger.debug("OS operation failed: %s", exc)


def _session_state(sync_type: str, sync_result: dict, count_fallback: bool, **extra) -> dict:
    all_states = WorkspaceRegistry.get_all_as_dict()
    all_sessions = WorkspaceRegistry.get_all_sessions()
    session_count = len(all_sessions)
    if count_fallback and not all_sessions:
        session_count = sum(len(ws.get("sessions", {})) for ws in all_states.values())
    return {
        "workspaces": all_states,
        "sessions": all_sessions,
        "workspace_count": len(all_states),
        "session_count": session_count,
        "last_sync": sync_result,
        "sync_type": sync_type,
        **extra,
        "updated_at": now_iso(),
    }


def _register_configured(configured_paths: set[str]) -> None:
    WorkspaceRegistry.load_from_disk()
    for workspace_path in configured_paths:
        uri = workspace_path if workspace_path.startswith("file://") else f"file://{workspace_path}"
        WorkspaceRegistry.get_or_create(uri, ensure_session=False)


def _ensure_loaded() -> None:
    if WorkspaceRegistry.count() == 0:
        WorkspaceRegistry.load_from_disk()


def recent_sync(tracker: SessionTracker) -> dict:
    """Full-detail sync of the recently active sessions."""
    _ensure_loaded()
    sync_result = WorkspaceRegistry.sync_sessions_with_cursor(session_ids=tracker.recent)
    write_state_file(_session_state("recent", sync_result, True, recent_sessions=list(tracker.recent)))
    return sync_result


def background_sync(tracker: SessionTracker) -> dict:
    """Sync the next batch of sessions that are not recently active."""
    _ensure_loaded()
    all_ids = [str(s["session_id"]) for s in WorkspaceRegistry.get_all_sessions() if s.get("session_id")]
    background_ids = [sid for sid in all_ids if sid not in tracker.recent]
    if not background_ids:
        logger.debug("No background sessions to sync")
        return dict(EMPTY_RESULT)

    batch_start, batch_ids = tracker.next_batch(background_ids)
    if not batch_ids:
        return dict(EMPTY_RESULT)
    logger.debug("Background sync batch: %d sessions (offset %d)", len(batch_ids), batch_start)

    sync_result = WorkspaceRegistry.sync_sessions_with_cursor(session_ids=batch_ids)
    write_state_file(
        _session_state(
            "background",
            sync_result,
            False,
            batch_offset=batch_start,
            batch_size=len(batch_ids),
            total_background=len(background_ids),
        )
    )
    logger.debug("Background sync: batch %d-%d, %s", batch_start, batch_start + tracker.batch_size, sync_result)
    return sync_result


def initial_sync(configured_paths: set[str]) -> int:
    """Lightweight startup sync (no content scan); returns the session count."""
    _register_configured(configured_paths)
    sync_result = WorkspaceRegistry.sync_all_with_cursor(skip_content_scan=True)
    state = _session_state("initial", sync_result, False)
    write_state_file(state)
    return len(state["sessions"])


def full_sync(configured_paths: set[str]) -> tuple[int, dict]:
    """Full sync of every workspace; returns the session count and sync result."""
    _register_configured(configured_paths)
    sync_result = WorkspaceRegistry.sync_all_with_cursor()
    state = _session_state("full", sync_result, True)
    write_state_file(state)
    return len(state["sessions"]), sync_result
