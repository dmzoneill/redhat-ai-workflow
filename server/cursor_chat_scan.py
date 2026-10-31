"""Scan Cursor chat content and meeting transcripts (issue keys, personas, projects).

Chat messages ("bubbles") live in Cursor's global ``state.vscdb`` under keys
``bubbleId:<chatId>:<bubbleId>``; meeting transcripts live in the meet bot database.
"""

import json
import logging
import re
import sqlite3
import subprocess
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from server import paths as server_paths
from server import utils as server_utils
from server.cursor_chat_db import CURSOR_DB_ERRORS, _valid_chat_id
from server.workspace_defaults import as_aware, from_epoch_ms

logger = logging.getLogger(__name__)

_ISSUE_KEY = re.compile(r"AAP-\d{4,7}", re.IGNORECASE)

# Valid persona names (from personas/ directory)
_VALID_PERSONAS = frozenset(
    {
        "admin",
        "code",
        "developer",
        "devops",
        "incident",
        "meetings",
        "observability",
        "performance",
        "project",
        "release",
        "researcher",
        "workspace",
        "slack",
        "core",
        "universal",
    }
)

# Patterns to detect persona loads (ordered by specificity)
_PERSONA_PATTERNS = (
    # persona_load("developer") or persona_load('developer')
    re.compile(r'persona_load\s*\(\s*["\'](\w+)["\']', re.IGNORECASE),
    # session_start(agent="devops") or agent='devops'
    re.compile(r'agent\s*=\s*["\'](\w+)["\']', re.IGNORECASE),
    # "Loaded persona: developer" or "Switched to persona: developer"
    re.compile(r'(?:Loaded|Switched to)\s+persona[:\s]+[`"\']?(\w+)[`"\']?', re.IGNORECASE),
    # "**Persona:** `developer`" (markdown output from session_start)
    re.compile(r"\*\*Persona:\*\*\s*`(\w+)`", re.IGNORECASE),
    # "Persona: developer" (plain text)
    re.compile(r'Persona:\s*[`"\']?(\w+)[`"\']?', re.IGNORECASE),
)

# Fallback when config.json cannot be read
_FALLBACK_PROJECTS = frozenset(
    {
        "automation-analytics-backend",
        "pdf-generator",
        "app-interface",
        "konflux-release-data",
        "redhat-ai-workflow",
    }
)

# Flexible patterns for spoken issue references in meeting transcripts
_SPOKEN_ISSUE_PATTERNS = (
    # Standard: AAP-12345 or AAP12345 or AAP 12345
    re.compile(r"\bAAP[-\s]?(\d{4,7})\b", re.IGNORECASE),
    # Spoken: "issue 12345" or "issue number 12345"
    re.compile(r"\bissue\s+(?:number\s+)?(\d{4,7})\b", re.IGNORECASE),
    # Spoken: "ticket 12345"
    re.compile(r"\bticket\s+(?:number\s+)?(\d{4,7})\b", re.IGNORECASE),
    # Spoken: "jira 12345"
    re.compile(r"\bjira\s+(?:issue\s+)?(?:number\s+)?(\d{4,7})\b", re.IGNORECASE),
)

_ISSUE_KEYS_SQL = "SELECT key, value FROM cursorDiskKV WHERE key LIKE ? AND value LIKE '%AAP-%' LIMIT 100"
_PERSONAS_SQL = """SELECT key, value FROM cursorDiskKV
                           WHERE key LIKE ?
                           AND (
                               value LIKE '%persona%'
                               OR value LIKE '%agent=%'
                               OR value LIKE '%Persona%'
                           )
                           LIMIT 50"""
_PROJECTS_SQL = """SELECT key, value FROM cursorDiskKV
                           WHERE key LIKE ?
                           AND (value LIKE '%project=%' OR value LIKE '%Project:%')
                           LIMIT 50"""
_TRANSCRIPTS_SQL = """
            SELECT t.meeting_id, t.text, m.title, m.scheduled_start
            FROM transcripts t
            JOIN meetings m ON t.meeting_id = m.id
            WHERE m.status = 'completed'
        """


def _global_db() -> Path:
    """Cursor's global state database."""
    return Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"


def _bubble_texts(conn: sqlite3.Connection, chat_ids: list[str], sql: str, what: str) -> Iterator[tuple[list, str]]:
    """Yield (key parts, text) of the matching bubbles of each chat (one query per chat)."""
    cursor = conn.cursor()
    for cid in chat_ids:
        try:
            cursor.execute(sql, (f"bubbleId:{cid}:%",))
            rows = cursor.fetchall()
        except sqlite3.Error as e:
            logger.debug("Error querying chat %s%s: %s", cid, what, e)
            continue
        for key, value in rows:
            parts = key.split(":")
            try:
                text = json.loads(value).get("text", "")
            except (json.JSONDecodeError, ValueError):
                continue
            if text:
                yield parts, text


def _bubble_position(parts: list) -> int:
    """Numeric bubble id used to order mentions (0 when not numeric)."""
    return int(parts[2]) if parts[2].isdigit() else 0


def _scan_issue_keys(conn: sqlite3.Connection, chat_ids: list[str]) -> dict[str, set[str]]:
    """Issue keys mentioned per chat."""
    chat_issue_sets: dict[str, set[str]] = {}
    for parts, text in _bubble_texts(conn, chat_ids, _ISSUE_KEYS_SQL, ""):
        if len(parts) < 2:
            continue
        matches = _ISSUE_KEY.findall(text)
        if matches:
            chat_issue_sets.setdefault(parts[1], set()).update(m.upper() for m in matches)
    return chat_issue_sets


def get_cursor_chat_issue_keys(chat_ids: list[str] | None = None) -> dict[str, str]:
    """Scan Cursor chat content for Jira issue keys (AAP-XXXXX pattern).

    Reads the global Cursor database to find issue references in chat messages.
    Returns all unique issue keys found in each chat, sorted and comma-separated.

    Uses Python sqlite3 module directly for better performance (no subprocess overhead).

    Args:
        chat_ids: Optional list of chat IDs to scan. If None, returns empty (too expensive).

    Returns:
        Dict mapping chat ID to comma-separated issue keys (e.g., "AAP-12345, AAP-12346")
    """
    # OPTIMIZATION: the daemon always provides specific IDs for targeted scanning
    if not chat_ids:
        logger.debug("get_cursor_chat_issue_keys: No chat_ids provided, skipping expensive full scan")
        return {}

    try:
        global_db = _global_db()
        if not global_db.exists():
            logger.debug("Cursor global storage not found")
            return {}

        with sqlite3.connect(str(global_db), timeout=10) as conn:
            chat_issue_sets = _scan_issue_keys(conn, chat_ids)

        # Sorted by the numeric part of the issue key, comma-separated
        result_map = {
            chat_id: ", ".join(sorted(issues, key=lambda x: int(x.split("-")[1])))
            for chat_id, issues in chat_issue_sets.items()
            if issues
        }
        if result_map:
            logger.debug("Found issue keys in %s chat(s)", len(result_map))
        return result_map

    except sqlite3.Error as e:
        logger.warning("SQLite error scanning for issue keys: %s", e)
        return {}
    # Best-effort: log and continue.
    except CURSOR_DB_ERRORS as e:
        logger.warning("Error scanning Cursor chats for issue keys: %s", e)
        return {}


def _empty_chat_content(chat_id: str) -> dict[str, Any]:
    """Result skeleton of get_cursor_chat_content."""
    return {
        "chat_id": chat_id,
        "message_count": 0,
        "messages": [],
        "summary": {
            "user_messages": 0,
            "assistant_messages": 0,
            "tool_calls": 0,
            "code_changes": 0,
            "issue_keys": [],
        },
    }


def _message_role(msg_type: Any) -> str:
    """Type 1 = user, Type 2 = assistant, anything else = system."""
    return {1: "user", 2: "assistant"}.get(msg_type, "system")


def _parse_bubble(line: str, summary: dict, issue_keys: set[str]) -> dict:
    """Parse one ``key|json`` output line into a message, updating summary counts."""
    key, value = line.split("|", 1)
    data = json.loads(value)

    parts = key.split(":")
    msg_role = _message_role(data.get("type", 0))
    text = data.get("text", "")
    created_at = data.get("createdAt")

    tool_results = []
    if data.get("toolResults"):
        tool_results = [
            str(tr["result"])[:200] for tr in data["toolResults"][:5] if isinstance(tr, dict) and tr.get("result")
        ]
        summary["tool_calls"] += len(data["toolResults"])

    code_chunks = []
    if data.get("attachedCodeChunks"):
        code_chunks = [chunk.get("filePath", "") for chunk in data["attachedCodeChunks"][:3] if isinstance(chunk, dict)]
        summary["code_changes"] += len(data["attachedCodeChunks"])

    if text:
        issue_keys.update(match.upper() for match in _ISSUE_KEY.findall(text))

    message = {
        "bubble_id": parts[2] if len(parts) >= 3 else "",
        "type": msg_role,
        "text": text[:2000] if text else "",  # Truncate long messages
        "timestamp": from_epoch_ms(created_at).isoformat() if created_at else None,
        "tool_results": tool_results or None,
        "code_chunks": code_chunks or None,
    }
    if msg_role == "user":
        summary["user_messages"] += 1
    elif msg_role == "assistant":
        summary["assistant_messages"] += 1
    return message


def _read_chat_bubbles(chat_id: str, max_messages: int, result: dict[str, Any]) -> None:
    """Query and parse all bubbles of a chat into ``result``."""
    global_db = _global_db()
    if not global_db.exists():
        logger.debug("Cursor global storage not found")
        return

    # chat_id is validated as a UUID by the caller
    query = f"SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:{chat_id}:%'"
    db_result = subprocess.run(
        ["sqlite3", str(global_db), query],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if db_result.returncode != 0:
        logger.debug("Failed to query Cursor global DB: %s", db_result.stderr)
        return

    messages_raw = []
    all_issue_keys: set[str] = set()
    for line in db_result.stdout.strip().split("\n"):
        if not line or "|" not in line:
            continue
        try:
            messages_raw.append(_parse_bubble(line, result["summary"], all_issue_keys))
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.debug("Error parsing bubble: %s", e)

    # Sort by timestamp if available, otherwise by bubble_id
    messages_raw.sort(key=lambda x: x.get("timestamp") or x.get("bubble_id") or "")
    result["messages"] = messages_raw[:max_messages]
    result["message_count"] = len(messages_raw)
    result["summary"]["issue_keys"] = sorted(all_issue_keys)
    logger.info("Extracted %s messages from chat %s...", len(messages_raw), chat_id[:8])


def get_cursor_chat_content(chat_id: str, max_messages: int = 50) -> dict:
    """Extract conversation content from a Cursor chat.

    Reads the global Cursor database to get all messages (bubbles) for a chat.
    Returns structured data including user messages, assistant responses,
    tool calls, code changes, and metadata.

    Args:
        chat_id: The Cursor chat/composer ID (UUID)
        max_messages: Maximum number of messages to return (default 50)

    Returns:
        Dict with chat content:
        {
            "chat_id": str,
            "message_count": int,
            "messages": [
                {
                    "type": "user" | "assistant",
                    "text": str,
                    "timestamp": str | None,
                    "tool_results": list[str] | None,
                    "code_chunks": list[str] | None,
                }
            ],
            "summary": {
                "user_messages": int,
                "assistant_messages": int,
                "tool_calls": int,
                "code_changes": int,
                "issue_keys": list[str],
            }
        }
    """
    result = _empty_chat_content(chat_id)

    # Validate chat_id is a valid UUID to prevent SQL injection
    if not _valid_chat_id(chat_id):
        return result

    try:
        _read_chat_bubbles(chat_id, max_messages, result)
    except subprocess.TimeoutExpired:
        logger.warning("Timeout extracting Cursor chat content")
    # Best-effort: log and continue.
    except CURSOR_DB_ERRORS as e:
        logger.warning("Error extracting Cursor chat content: %s", e)
    return result


def _session_metadata_lines(session: Any) -> list[str]:
    """Jira lines describing the session (id, persona, project, branch, timing)."""
    lines = [f"*Session ID:* {session.session_id[:8]}...", f"*Persona:* {session.persona}"]
    if session.project:
        lines.append(f"*Project:* {session.project}")
    if session.branch:
        lines.append(f"*Branch:* {{monospace}}{session.branch}{{monospace}}")
    if session.started_at:
        lines.append(f"*Started:* {session.started_at.strftime('%Y-%m-%d %H:%M')}")
    if session.last_activity:
        duration = as_aware(session.last_activity) - as_aware(session.started_at)
        minutes = int(duration.total_seconds() / 60)
        lines.append(f"*Duration:* ~{minutes} minutes")
    lines.append("")
    return lines


def _key_actions(messages: list[dict]) -> list[str]:
    """One-line summaries of the assistant's tool results."""
    actions = []
    for msg in messages:
        if msg.get("type") != "assistant" or not msg.get("tool_results"):
            continue
        for tr in msg["tool_results"][:3]:
            if tr and len(tr) > 10:
                action = tr[:100].replace("\n", " ").strip()
                if action:
                    actions.append(action)
    return actions


def _transcript_lines(messages: list[dict], max_chars: int) -> list[str]:
    """Collapsible transcript block, truncated after ``max_chars`` characters."""
    lines = ["{expand:Full Transcript}", "{code}"]
    transcript_chars = 0
    for msg in messages:
        if transcript_chars >= max_chars:
            lines.append("... (truncated)")
            break
        role = msg.get("type", "unknown").upper()
        text = msg.get("text", "")[:500]  # Truncate individual messages
        timestamp = msg.get("timestamp", "")[:16] if msg.get("timestamp") else ""
        entry = f"[{timestamp}] {role}: {text}\n"
        lines.append(entry)
        transcript_chars += len(entry)
    lines.extend(["{code}", "{expand}"])
    return lines


def format_session_context_for_jira(
    chat_content: dict,
    session: Any = None,
    include_transcript: bool = False,
    max_transcript_chars: int = 5000,
) -> str:
    """Format session context as Jira wiki markup.

    Creates a well-formatted comment for Jira that summarizes the AI session,
    including key actions, tool calls, and optionally the full transcript.

    Args:
        chat_content: Output from get_cursor_chat_content()
        session: Optional ChatSession for additional metadata
        include_transcript: Whether to include full conversation transcript
        max_transcript_chars: Max chars for transcript (default 5000)

    Returns:
        Jira wiki markup formatted string
    """
    lines = ["{panel:title=AI Session Context|borderStyle=solid|borderColor=#0052CC}"]
    if session:
        lines.extend(_session_metadata_lines(session))

    summary = chat_content.get("summary", {})
    lines.append("h3. Summary")
    lines.append(
        f"* *Messages:* {summary.get('user_messages', 0)} user, {summary.get('assistant_messages', 0)} assistant"
    )
    lines.append(f"* *Tool Calls:* {summary.get('tool_calls', 0)}")
    lines.append(f"* *Code References:* {summary.get('code_changes', 0)}")
    issue_keys = summary.get("issue_keys", [])
    if issue_keys:
        lines.append(f"* *Related Issues:* {', '.join(issue_keys)}")
    lines.append("")

    messages = chat_content.get("messages", [])
    key_actions = _key_actions(messages)
    if key_actions:
        lines.append("h3. Key Actions")
        lines.extend(f"* {action}" for action in key_actions[:10])  # Limit to 10 actions
        lines.append("")

    if include_transcript and messages:
        lines.extend(_transcript_lines(messages, max_transcript_chars))

    lines.append("{panel}")
    return "\n".join(lines)


def _last_personas(conn: sqlite3.Connection, chat_ids: list[str]) -> dict[str, str]:
    """Last (highest bubble id) valid persona mentioned in each chat."""
    chat_personas: dict[str, list[tuple[int, str]]] = {}
    for parts, text in _bubble_texts(conn, chat_ids, _PERSONAS_SQL, " for personas"):
        if len(parts) < 3:
            continue
        position = _bubble_position(parts)
        for pattern in _PERSONA_PATTERNS:
            for match in pattern.findall(text):
                persona = match.lower()
                if persona in _VALID_PERSONAS:
                    chat_personas.setdefault(parts[1], []).append((position, persona))

    result_map = {}
    for chat_id, persona_list in chat_personas.items():
        persona_list.sort(key=lambda x: x[0])
        result_map[chat_id] = persona_list[-1][1]
    return result_map


def get_cursor_chat_personas(chat_ids: list[str] | None = None) -> dict[str, str]:
    """Scan Cursor chat content to detect the last persona loaded in each chat.

    Looks for patterns like:
    - persona_load("developer") or persona_load('developer')
    - session_start(agent="devops") or session_start(agent='devops')
    - "Loaded persona: developer" (tool output)
    - "Persona:** `developer`" (session_start output)

    Uses Python sqlite3 module directly for better performance.

    Args:
        chat_ids: Optional list of chat IDs to scan. If None, returns empty (too expensive).

    Returns:
        Dict mapping chat ID to the last detected persona name.
    """
    if not chat_ids:
        logger.debug("get_cursor_chat_personas: No chat_ids provided, skipping expensive full scan")
        return {}

    try:
        global_db = _global_db()
        if not global_db.exists():
            logger.debug("Cursor global storage not found")
            return {}

        with sqlite3.connect(str(global_db), timeout=10) as conn:
            result_map = _last_personas(conn, chat_ids)

        if result_map:
            logger.debug("Detected personas in %s chat(s) from content", len(result_map))
        return result_map

    except sqlite3.Error as e:
        logger.warning("SQLite error scanning for personas: %s", e)
        return {}
    # Best-effort: log and continue.
    except CURSOR_DB_ERRORS as e:
        logger.warning("Error scanning Cursor chats for personas: %s", e)
        return {}


def _valid_projects() -> set[str]:
    """Project names from config.json (a known fallback list when unreadable)."""
    try:
        return set(server_utils.load_config().get("repositories", {}).keys())
    # Best-effort fallback to known projects.
    except CURSOR_DB_ERRORS:
        return set(_FALLBACK_PROJECTS)


def _project_patterns(projects: set[str]) -> list[tuple[re.Pattern, int]]:
    """(pattern, priority) pairs recognising mentions of each project."""
    patterns = []
    for proj in projects:
        escaped = re.escape(proj)
        patterns.extend(
            [
                (re.compile(rf'project\s*=\s*["\']({escaped})["\']', re.IGNORECASE), 10),
                (re.compile(rf"\*\*Project:\*\*\s*`({escaped})`", re.IGNORECASE), 9),
                (re.compile(rf'Project:\s*[`"\']?({escaped})[`"\']?', re.IGNORECASE), 8),
                (re.compile(rf"/(?:home|Users)/[^/]+/(?:src|projects?|repos?)/({escaped})/", re.IGNORECASE), 7),
                (re.compile(rf'[\w-]+/({escaped})(?:\s|$|["\'\]])', re.IGNORECASE), 6),
                (re.compile(rf"\b({escaped})\b", re.IGNORECASE), 5),
            ]
        )
    return patterns


def _canonical_project(name: str, projects: set[str]) -> str:
    """Configured spelling of a (lower-cased) project name."""
    return next((proj for proj in projects if proj.lower() == name), name)


def _project_mentions(text: str, patterns: list[tuple[re.Pattern, int]], projects: set[str]) -> list[tuple[int, str]]:
    """(priority, configured project) for every project mention in ``text``."""
    mentions = []
    for pattern, priority in patterns:
        for match in pattern.findall(text):
            project_name = _canonical_project(match.lower(), projects)
            if project_name in projects:
                mentions.append((priority, project_name))
    return mentions


def _best_projects(conn: sqlite3.Connection, chat_ids: list[str], projects: set[str]) -> dict[str, str]:
    """Highest-priority, latest project mention per chat (redhat-ai-workflow ignored)."""
    patterns = _project_patterns(projects)
    chat_projects: dict[str, list[tuple[int, int, str]]] = {}
    for parts, text in _bubble_texts(conn, chat_ids, _PROJECTS_SQL, " for projects"):
        if len(parts) < 3:
            continue
        position = _bubble_position(parts)
        for priority, project_name in _project_mentions(text, patterns, projects):
            chat_projects.setdefault(parts[1], []).append((position, priority, project_name))

    result_map = {}
    for chat_id, project_list in chat_projects.items():
        project_list.sort(key=lambda x: (x[1], x[0]), reverse=True)
        best_project = project_list[0][2]
        if best_project != "redhat-ai-workflow":
            result_map[chat_id] = best_project
    return result_map


def get_cursor_chat_projects(chat_ids: list[str] | None = None) -> dict[str, str]:
    """Scan Cursor chat content to detect the project being worked on in each chat.

    Looks for patterns like:
    - session_start(project="automation-analytics-backend")
    - session_set_project(project="pdf-generator")
    - Repository names: "automation-analytics-backend", "pdf-generator"
    - GitLab paths: "automation-analytics/automation-analytics-backend"
    - File paths: "/home/.../automation-analytics-backend/..."
    - **Project:** `automation-analytics-backend` (session_start output)

    Uses Python sqlite3 module directly for better performance.

    Args:
        chat_ids: Optional list of chat IDs to scan. If None, returns empty (too expensive).

    Returns:
        Dict mapping chat ID to the detected project name.
    """
    if not chat_ids:
        logger.debug("get_cursor_chat_projects: No chat_ids provided, skipping expensive full scan")
        return {}

    projects = _valid_projects()
    if not projects:
        return {}

    try:
        global_db = _global_db()
        if not global_db.exists():
            logger.debug("Cursor global storage not found")
            return {}

        with sqlite3.connect(str(global_db), timeout=10) as conn:
            result_map = _best_projects(conn, chat_ids, projects)

        if result_map:
            logger.debug("Detected projects in %s chat(s) from content", len(result_map))
        return result_map

    except sqlite3.Error as e:
        logger.warning("SQLite error scanning for projects: %s", e)
        return {}
    # Best-effort: log and continue.
    except CURSOR_DB_ERRORS as e:
        logger.warning("Error scanning Cursor chats for projects: %s", e)
        return {}


def _record_transcript_line(line: str, issue_keys: list[str] | None, issue_meetings: dict) -> None:
    """Count the issue references of one ``id|||text|||title|||start`` row."""
    parts = line.split("|||")
    if len(parts) < 4:
        return
    meeting_id = int(parts[0])
    text, title = parts[1], parts[2]
    date = parts[3][:10] if parts[3] else ""  # Just the date part

    found_numbers = {match.group(1) for pattern in _SPOKEN_ISSUE_PATTERNS for match in pattern.finditer(text)}
    for number in found_numbers:
        issue_key = f"AAP-{number}"
        if issue_keys and issue_key not in issue_keys:
            continue
        info = issue_meetings[issue_key][meeting_id]
        info["title"] = title
        info["date"] = date
        info["count"] += 1


def get_meeting_transcript_issue_keys(
    issue_keys: list[str] | None = None,
) -> dict[str, list[dict]]:
    """Scan meeting transcripts for Jira issue keys.

    Searches the meet_bot database for mentions of issue keys in transcripts.
    Uses flexible matching to handle spoken variations like:
    - "AAP 12345" (without hyphen)
    - "issue 12345" or "issue number 12345"
    - "aap twelve three four five" (spelled out - future enhancement)
    - "ticket 12345"

    Args:
        issue_keys: Optional list of issue keys to search for.
            If None, finds all AAP-XXXXX patterns.

    Returns:
        Dict mapping issue key to list of meeting info dicts:
        {
            "AAP-12345": [
                {"meeting_id": 1, "title": "Sprint Planning", "date": "2025-01-20", "matches": 3},
                ...
            ]
        }
    """
    try:
        db_path = server_paths.MEETINGS_DB_FILE
        if not db_path.exists():
            logger.debug("Meet bot database not found")
            return {}

        result = subprocess.run(
            ["sqlite3", "-separator", "|||", str(db_path), _TRANSCRIPTS_SQL],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            logger.debug("Failed to query meet bot DB: %s", result.stderr)
            return {}

        # {issue_key: {meeting_id: {"title": ..., "date": ..., "count": N}}}
        issue_meetings: dict[str, dict[int, dict]] = defaultdict(
            lambda: defaultdict(lambda: {"title": "", "date": "", "count": 0})
        )
        for line in result.stdout.strip().split("\n"):
            if not line or "|||" not in line:
                continue
            try:
                _record_transcript_line(line, issue_keys, issue_meetings)
            except (ValueError, IndexError):
                continue

        result_map: dict[str, list[dict]] = {
            issue_key: [
                {"meeting_id": mid, "title": info["title"], "date": info["date"], "matches": info["count"]}
                for mid, info in sorted(meetings.items(), key=lambda x: x[1]["date"], reverse=True)
            ]
            for issue_key, meetings in issue_meetings.items()
        }
        if result_map:
            logger.info("Found %s issue(s) mentioned in meeting transcripts", len(result_map))
        return result_map

    except subprocess.TimeoutExpired:
        logger.warning("Timeout scanning meet bot DB for issue keys")
        return {}
    # Best-effort: log and continue.
    except CURSOR_DB_ERRORS as e:
        logger.warning("Error scanning meeting transcripts for issue keys: %s", e)
        return {}
