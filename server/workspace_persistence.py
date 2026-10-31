"""Rebuilding workspaces and sessions from the persisted workspace_states.json data."""

import logging
from datetime import datetime
from typing import Any

from server import workspace_defaults
from server.chat_session import ChatSession
from server.workspace_model import WorkspaceState

logger = logging.getLogger(__name__)

_SESSION_TIMESTAMPS = ("started_at", "last_activity", "last_filter_time", "last_tool_time")
_WORKSPACE_TIMESTAMPS = ("created_at", "last_activity")


def _restore_timestamps(target: Any, data: dict, names: tuple[str, ...]) -> None:
    """Set ISO timestamps from ``data`` on ``target``, keeping defaults for unparsable values."""
    for name in names:
        if not data.get(name):
            continue
        try:
            setattr(target, name, datetime.fromisoformat(data[name]))
        except (ValueError, TypeError) as exc:
            logger.debug("Suppressed error: %s", exc)


def _static_tool_count(sess_data: dict) -> int | None:
    """Tool count from the new format, or derived from the old tool_count / active_tools."""
    if sess_data.get("static_tool_count"):
        return sess_data["static_tool_count"]
    if sess_data.get("tool_count"):
        # Old format: tool_count was the static count
        return sess_data["tool_count"]
    if sess_data.get("active_tools"):
        return len(sess_data["active_tools"])
    return None


def session_from_dict(session_id: str, workspace: WorkspaceState, sess_data: dict) -> ChatSession:
    """Rebuild a persisted session; sessions without a project inherit the workspace's."""
    session_project = sess_data.get("project")
    session_auto_detected = sess_data.get("is_project_auto_detected", False)
    if session_project is None:
        session_project = workspace.project
        session_auto_detected = workspace.is_auto_detected

    session = ChatSession(
        session_id=session_id,
        workspace_uri=workspace.workspace_uri,
        persona=sess_data.get("persona", workspace_defaults.get_default_persona()),
        project=session_project,
        is_project_auto_detected=session_auto_detected,
        issue_key=sess_data.get("issue_key"),
        branch=sess_data.get("branch"),
        name=sess_data.get("name"),
    )
    _restore_timestamps(session, sess_data, _SESSION_TIMESTAMPS)

    static_count = _static_tool_count(sess_data)
    if static_count is not None:
        session.static_tool_count = static_count
    session.dynamic_tool_count = sess_data.get("dynamic_tool_count", 0)
    session.last_filter_message = sess_data.get("last_filter_message")
    session.last_tool = sess_data.get("last_tool")
    session.tool_call_count = sess_data.get("tool_call_count", 0)
    session.meeting_references = sess_data.get("meeting_references", [])
    return session


def workspace_from_dict(workspace_uri: str, ws_data: dict, project: str | None, auto_detected: bool) -> WorkspaceState:
    """Rebuild a persisted workspace (with the given project) and all its sessions."""
    workspace = WorkspaceState(workspace_uri=workspace_uri)
    workspace.project = project
    workspace.is_auto_detected = auto_detected
    workspace.active_session_id = ws_data.get("active_session_id")
    _restore_timestamps(workspace, ws_data, _WORKSPACE_TIMESTAMPS)

    for session_id, sess_data in ws_data.get("sessions", {}).items():
        workspace.sessions[session_id] = session_from_dict(session_id, workspace, sess_data)
    return workspace


def find_persisted_uri(workspace_uri: str, workspaces_data: dict) -> str | None:
    """The persisted key for ``workspace_uri`` (ignoring trailing slashes), if any."""
    if workspace_uri in workspaces_data:
        return workspace_uri
    normalized_uri = workspace_uri.rstrip("/")
    return next((uri for uri in workspaces_data if uri.rstrip("/") == normalized_uri), None)
