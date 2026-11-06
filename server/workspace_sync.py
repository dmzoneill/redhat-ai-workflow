"""Steps of WorkspaceState.sync_with_cursor_db (keeping sessions in sync with Cursor's database)."""

import logging
import re
from typing import Any, NamedTuple

from server import cursor_chat_scan, workspace_defaults
from server.chat_session import ChatSession

logger = logging.getLogger(__name__)

# Pattern: AAP-XXXXX (4-7 digits, case insensitive)
_ISSUE_KEY = re.compile(r"AAP-\d{4,7}", re.IGNORECASE)


class ContentScan(NamedTuple):
    """Results of the (expensive) chat content scans."""

    issue_keys: dict[str, str]
    personas: dict[str, str]
    projects: dict[str, str]


class SyncInputs(NamedTuple):
    """Everything a sync pass needs to know about Cursor's chats."""

    chat_map: dict[str, dict]  # composerId -> chat
    issue_keys: dict[str, str]  # composerId -> "AAP-1, AAP-2"
    scan: ContentScan
    current_tool_count: int  # Tools loaded for the active session


def _issue_sort_key(key: str) -> int:
    """Numeric part of an issue key."""
    return int(key.split("-")[1])


def scan_content(scan_ids: list[str]) -> ContentScan:
    """Scan chat content for issue keys, persona loads and project mentions (queries the large global DB)."""
    if not scan_ids:
        return ContentScan({}, {}, {})
    return ContentScan(
        cursor_chat_scan.get_cursor_chat_issue_keys(scan_ids),
        cursor_chat_scan.get_cursor_chat_personas(scan_ids),
        cursor_chat_scan.get_cursor_chat_projects(scan_ids),
    )


def merge_issue_keys(chat_map: dict[str, dict], from_content: dict[str, str]) -> dict[str, str]:
    """Issue keys per chat from its name (cheap) and content scan, deduplicated and sorted."""
    issue_keys: dict[str, str] = {}
    for sid, chat in chat_map.items():
        all_keys = {m.upper() for m in _ISSUE_KEY.findall(chat.get("name") or "")}
        if sid in from_content:
            all_keys.update(k.strip() for k in from_content[sid].split(","))
        if all_keys:
            issue_keys[sid] = ", ".join(sorted(all_keys, key=_issue_sort_key))
    return issue_keys


def session_from_cursor_chat(workspace: Any, sid: str, inputs: SyncInputs) -> ChatSession:
    """Minimal session for a Cursor chat that never called session_start()."""
    cursor_chat = inputs.chat_map[sid]
    logger.info("Adding session %s from Cursor DB: %s", sid, cursor_chat.get("name"))

    detected_persona = inputs.scan.personas.get(sid)
    session_persona = detected_persona or workspace_defaults.get_default_persona()
    if detected_persona:
        logger.info("Detected persona '%s' from chat content for %s", detected_persona, sid)

    detected_project = inputs.scan.projects.get(sid)
    if detected_project:
        logger.info("Detected project '%s' from chat content for %s", detected_project, sid)

    session = ChatSession(
        session_id=sid,
        workspace_uri=workspace.workspace_uri,
        persona=session_persona,
        project=detected_project or workspace.project,
        is_project_auto_detected=detected_project is None and workspace.is_auto_detected,
        name=cursor_chat.get("name"),
        static_tool_count=workspace_defaults.get_persona_tool_count(session_persona),
        issue_key=inputs.issue_keys.get(sid),
    )
    # Cursor's timestamps are milliseconds
    if cursor_chat.get("lastUpdatedAt"):
        session.last_activity = workspace_defaults.from_epoch_ms(cursor_chat["lastUpdatedAt"])
        session.started_at = workspace_defaults.from_epoch_ms(
            cursor_chat.get("createdAt", cursor_chat["lastUpdatedAt"])
        )
    return session


def sync_name(session: ChatSession, cursor_chat: dict) -> bool:
    """Take Cursor's chat name; clear the "unnamed" placeholder. True when renamed."""
    cursor_name = cursor_chat.get("name")
    if cursor_name and cursor_name != session.name:
        logger.debug("Renaming session %s: '%s' -> '%s'", session.session_id, session.name, cursor_name)
        session.name = cursor_name
        return True
    # Clear "unnamed" placeholder so UI uses better fallback
    if not cursor_name and session.name == "unnamed":
        session.name = None
        return True
    return False


def _sync_activity(session: ChatSession, cursor_chat: dict) -> bool:
    """Advance last_activity to Cursor's lastUpdatedAt."""
    if not cursor_chat.get("lastUpdatedAt"):
        return False
    cursor_last_activity = workspace_defaults.from_epoch_ms(cursor_chat["lastUpdatedAt"])
    if session.last_activity is None or cursor_last_activity > workspace_defaults.as_aware(session.last_activity):
        session.last_activity = cursor_last_activity
        return True
    return False


def _sync_tool_count(session: ChatSession, is_active: bool, current_tool_count: int) -> bool:
    """Active session: loaded tools; inactive with no count: cached persona tool count."""
    if is_active and current_tool_count > 0:
        if session.static_tool_count != current_tool_count:
            session.static_tool_count = current_tool_count
            return True
        return False
    if session.static_tool_count == 0:
        persona_count = workspace_defaults.get_persona_tool_count(session.persona)
        if persona_count > 0:
            session.static_tool_count = persona_count
            return True
    return False


def _sync_issue_key(session: ChatSession, issue_keys: dict[str, str]) -> bool:
    """Set the issue key when not already set and found in the chat."""
    sid = session.session_id
    if session.issue_key or sid not in issue_keys:
        return False
    session.issue_key = issue_keys[sid]
    logger.info("Found issue key %s in chat %s", issue_keys[sid], sid)
    return True


def _sync_persona(session: ChatSession, personas: dict[str, str]) -> bool:
    """Replace a generic/default persona with the one detected in the chat content."""
    generic_personas = {workspace_defaults.get_default_persona(), "workspace"}
    detected_persona = personas.get(session.session_id)
    if session.persona not in generic_personas or detected_persona is None:
        return False
    if detected_persona in generic_personas:
        return False
    logger.info(
        "Updating persona for %s from chat content: '%s' -> '%s'",
        session.session_id,
        session.persona,
        detected_persona,
    )
    session.persona = detected_persona
    new_tool_count = workspace_defaults.get_persona_tool_count(detected_persona)
    if new_tool_count > 0:
        session.static_tool_count = new_tool_count
    return True


def _sync_project(session: ChatSession, projects: dict[str, str]) -> bool:
    """Replace an auto-detected (workspace default) project with one detected in the chat."""
    if not session.is_project_auto_detected or session.session_id not in projects:
        return False
    detected_project = projects[session.session_id]
    if not detected_project or detected_project == session.project:
        return False
    logger.info(
        "Updating project for %s from chat content: '%s' -> '%s'",
        session.session_id,
        session.project,
        detected_project,
    )
    session.project = detected_project
    session.is_project_auto_detected = False  # Now explicitly detected
    return True


def update_existing_session(session: ChatSession, is_active: bool, inputs: SyncInputs) -> bool:
    """Apply activity, tool count, issue key, persona and project updates. True when anything changed."""
    cursor_chat = inputs.chat_map[session.session_id]
    changes = [
        _sync_activity(session, cursor_chat),
        _sync_tool_count(session, is_active, inputs.current_tool_count),
        _sync_issue_key(session, inputs.issue_keys),
        _sync_persona(session, inputs.scan.personas),
        _sync_project(session, inputs.scan.projects),
    ]
    return any(changes)


def _session_issue_keys(session: ChatSession) -> list[str]:
    """The session's issue keys as a list."""
    return [k.strip() for k in session.issue_key.split(", ")] if session.issue_key else []


def _merged_meetings(keys: list[str], meeting_refs: dict[str, list[dict]]) -> list[dict]:
    """Meetings mentioning any of ``keys``, match counts summed, most recent first."""
    all_meetings: dict[int, dict] = {}  # meeting_id -> meeting info
    for key in keys:
        for meeting in meeting_refs.get(key, []):
            mid = meeting["meeting_id"]
            if mid not in all_meetings:
                all_meetings[mid] = meeting.copy()
            else:
                all_meetings[mid]["matches"] += meeting["matches"]
    return sorted(all_meetings.values(), key=lambda x: x.get("date", ""), reverse=True)


def refresh_meeting_references(sessions: list[ChatSession]) -> None:
    """Attach meetings whose transcripts mention each session's issue keys."""
    all_issue_keys = {key for session in sessions for key in _session_issue_keys(session)}
    if not all_issue_keys:
        return

    meeting_refs = cursor_chat_scan.get_meeting_transcript_issue_keys(list(all_issue_keys))
    for session in sessions:
        if not session.issue_key:
            continue
        new_refs = _merged_meetings(_session_issue_keys(session), meeting_refs)
        if new_refs != session.meeting_references:
            session.meeting_references = new_refs
            if new_refs:
                logger.debug("Session %s has %s meeting reference(s)", session.session_id[:8], len(new_refs))
