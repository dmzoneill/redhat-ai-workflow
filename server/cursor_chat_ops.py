"""Cursor Chat Operations - Read/write Cursor IDE chat data.

Standalone functions for interacting with Cursor's SQLite databases and
workspace storage. These operations are separate from WorkspaceState/WorkspaceRegistry
to keep the workspace state module focused on session management.

All functions in this module operate on Cursor's internal storage:
- workspaceStorage: Per-workspace composer metadata (state.vscdb)
- globalStorage: Cross-workspace chat content (state.vscdb)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.workspace_state import ChatSession

logger = logging.getLogger(__name__)

# Transcript/content limits for chat extraction
MAX_TOOL_RESULTS_IN_TRANSCRIPT = 5
MAX_TOOL_RESULT_CHARS = 200
MAX_CODE_CHUNKS_IN_TRANSCRIPT = 3
MAX_MESSAGE_TEXT_CHARS = 2000
DEFAULT_MAX_TRANSCRIPT_CHARS = 5000


def _cursor_workspace_storage() -> Path:
    """Get Cursor workspace storage path at runtime.

    Computed dynamically so that tests can patch Path.home().
    """
    return Path.home() / ".config" / "Cursor" / "User" / "workspaceStorage"


def _read_storage_dir_composer_data(
    storage_dir: Path, workspace_uri: str
) -> tuple[dict | None, str]:
    """Read composer data from a storage dir. Returns (data, status).
    status: 'ok' | 'no_match' | 'read_failed'"""
    import subprocess

    workspace_json = storage_dir / "workspace.json"
    if not workspace_json.exists():
        return None, "no_match"
    try:
        workspace_data = json.loads(workspace_json.read_text())
    except (json.JSONDecodeError, KeyError):
        return None, "no_match"
    folder_uri = workspace_data.get("folder", "")
    if folder_uri != workspace_uri:
        return None, "no_match"
    db_path = storage_dir / "state.vscdb"
    if not db_path.exists():
        return None, "no_match"
    query = "SELECT value FROM ItemTable WHERE key = 'composer.composerData'"
    result = subprocess.run(
        ["sqlite3", str(db_path), query],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None, "read_failed"
    try:
        return json.loads(result.stdout.strip()), "ok"
    except json.JSONDecodeError:
        return None, "read_failed"


def get_cursor_chat_info_from_db(workspace_uri: str) -> tuple[str | None, str | None]:
    """Read Cursor's database to get the current chat's UUID and name.

    Cursor stores chat data in workspace-specific SQLite databases.
    We find the most recently updated chat for this workspace and return its ID and name.

    Args:
        workspace_uri: The workspace URI (e.g., "file:///home/user/project")

    Returns:
        Tuple of (chat_id, chat_name) if found, (None, None) otherwise
    """
    try:
        workspace_storage_dir = _cursor_workspace_storage()
        if not workspace_storage_dir.exists():
            logger.debug("Cursor workspace storage not found")
            return None, None

        for storage_dir in workspace_storage_dir.iterdir():
            if not storage_dir.is_dir():
                continue
            composer_data, status = _read_storage_dir_composer_data(
                storage_dir, workspace_uri
            )
            if status == "no_match":
                continue
            if status == "read_failed":
                return None, None
            all_composers = composer_data.get("allComposers", [])
            if not all_composers:
                logger.debug("No composers found in database")
                return None, None
            active_chats = [
                c
                for c in all_composers
                if not c.get("isArchived") and not c.get("isDraft")
            ]
            if not active_chats:
                logger.debug("No active chats found")
                return None, None
            most_recent = max(active_chats, key=lambda x: x.get("lastUpdatedAt", 0))
            chat_id = most_recent.get("composerId")
            chat_name = most_recent.get("name")
            logger.info(f"Found Cursor chat: {chat_id} ({chat_name})")
            return chat_id, chat_name

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


def list_cursor_chats(workspace_uri: str) -> tuple[list[dict], str | None]:
    """List all Cursor chats for a workspace and get the active chat ID.

    Cursor may have multiple storage directories for the same workspace URI
    (e.g., from reopening the same folder). This function aggregates chats
    from all matching directories and deduplicates by composerId.

    Args:
        workspace_uri: The workspace URI

    Returns:
        Tuple of (list of chat info dicts, active_chat_id or None)
    """
    try:
        workspace_storage_dir = _cursor_workspace_storage()
        if not workspace_storage_dir.exists():
            return [], None

        all_chats: dict[str, dict] = {}
        active_chat_id = None

        for storage_dir in workspace_storage_dir.iterdir():
            if not storage_dir.is_dir():
                continue
            composer_data, status = _read_storage_dir_composer_data(
                storage_dir, workspace_uri
            )
            if status != "ok":
                continue

            all_composers = composer_data.get("allComposers", [])
            last_focused = composer_data.get("lastFocusedComposerIds", [])
            if last_focused and not active_chat_id:
                active_chat_id = last_focused[0]

            for c in all_composers:
                if c.get("isArchived") or c.get("isDraft"):
                    continue
                if c.get("name") is None and c.get("lastUpdatedAt") is None:
                    continue
                composer_id = c.get("composerId")
                if not composer_id:
                    continue

                chat_dict = {
                    "composerId": composer_id,
                    "name": c.get("name"),
                    "createdAt": c.get("createdAt", 0),
                    "lastUpdatedAt": c.get("lastUpdatedAt", 0),
                    "isArchived": c.get("isArchived", False),
                    "isDraft": c.get("isDraft", False),
                }
                if (
                    composer_id not in all_chats
                    or chat_dict["lastUpdatedAt"]
                    > all_chats[composer_id]["lastUpdatedAt"]
                ):
                    all_chats[composer_id] = chat_dict

        chats = sorted(
            all_chats.values(), key=lambda x: x["lastUpdatedAt"], reverse=True
        )
        return chats, active_chat_id

    except Exception as e:
        logger.warning(f"Error listing Cursor chats: {e}")
        return [], None


def get_cursor_chat_ids(workspace_uri: str) -> set[str]:
    """Get all active Cursor chat IDs for a workspace.

    Args:
        workspace_uri: The workspace URI

    Returns:
        Set of chat IDs that exist in Cursor's database
    """
    chats, _ = list_cursor_chats(workspace_uri)
    return {c["composerId"] for c in chats if c.get("composerId")}


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
    import re
    import sqlite3

    # OPTIMIZATION: If no specific chat IDs provided, skip the expensive full scan
    # The daemon should always provide specific IDs for targeted scanning
    if not chat_ids:
        logger.debug(
            "get_cursor_chat_issue_keys: No chat_ids provided, skipping expensive full scan"
        )
        return {}

    try:
        global_db = (
            Path.home()
            / ".config"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )
        if not global_db.exists():
            logger.debug("Cursor global storage not found")
            return {}

        chat_issue_sets: dict[str, set[str]] = {}
        issue_pattern = re.compile(r"AAP-\d{4,7}", re.IGNORECASE)

        conn = sqlite3.connect(str(global_db), timeout=10)
        try:
            cursor = conn.cursor()

            for cid in chat_ids:
                try:
                    cursor.execute(
                        "SELECT key, value FROM cursorDiskKV WHERE key LIKE ? AND value LIKE '%AAP-%' LIMIT 100",
                        (f"bubbleId:{cid}:%",),
                    )

                    for key, value in cursor.fetchall():
                        try:
                            parts = key.split(":")
                            if len(parts) < 2:
                                continue
                            chat_id = parts[1]
                            data = json.loads(value)
                            text = data.get("text", "")
                            if not text:
                                continue
                            matches = issue_pattern.findall(text)
                            if not matches:
                                continue
                            if chat_id not in chat_issue_sets:
                                chat_issue_sets[chat_id] = set()
                            for m in matches:
                                chat_issue_sets[chat_id].add(m.upper())
                        except (json.JSONDecodeError, ValueError):
                            continue
                except sqlite3.Error as e:
                    logger.debug(f"Error querying chat {cid}: {e}")
                    continue
        finally:
            conn.close()

        # Return sorted, comma-separated issue keys for each chat
        result_map = {}
        for chat_id, issues in chat_issue_sets.items():
            if issues:
                # Sort by the numeric part of the issue key
                sorted_issues = sorted(issues, key=lambda x: int(x.split("-")[1]))
                result_map[chat_id] = ", ".join(sorted_issues)

        if result_map:
            logger.debug(f"Found issue keys in {len(result_map)} chat(s)")

        return result_map

    except sqlite3.Error as e:
        logger.warning(f"SQLite error scanning for issue keys: {e}")
        return {}
    except Exception as e:
        logger.warning(f"Error scanning Cursor chats for issue keys: {e}")
        return {}


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
    import re
    import subprocess
    import uuid

    result = {
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

    # Validate chat_id is a valid UUID to prevent SQL injection
    try:
        uuid.UUID(chat_id)
    except (ValueError, TypeError):
        logger.warning(
            f"Invalid chat_id format (expected UUID): {chat_id[:50] if chat_id else 'None'}"
        )
        return result

    try:
        global_db = (
            Path.home()
            / ".config"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )
        if not global_db.exists():
            logger.debug("Cursor global storage not found")
            return result

        # Query all bubbles for this chat - chat_id is validated as UUID above
        query = (
            f"SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:{chat_id}:%'"
        )
        db_result = subprocess.run(
            ["sqlite3", str(global_db), query],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if db_result.returncode != 0:
            logger.debug(f"Failed to query Cursor global DB: {db_result.stderr}")
            return result

        # Parse messages
        messages_raw = []
        issue_pattern = re.compile(r"AAP-\d{4,7}", re.IGNORECASE)
        all_issue_keys: set[str] = set()

        for line in db_result.stdout.strip().split("\n"):
            if not line or "|" not in line:
                continue
            try:
                key, value = line.split("|", 1)
                data = json.loads(value)

                # Extract bubble ID for ordering
                parts = key.split(":")
                bubble_id = parts[2] if len(parts) >= 3 else ""

                msg_type = data.get("type", 0)
                text = data.get("text", "")
                created_at = data.get("createdAt")

                # Type 1 = user, Type 2 = assistant
                msg_role = (
                    "user"
                    if msg_type == 1
                    else "assistant" if msg_type == 2 else "system"
                )

                # Extract tool results
                tool_results = []
                if data.get("toolResults"):
                    for tr in data["toolResults"][:MAX_TOOL_RESULTS_IN_TRANSCRIPT]:
                        if isinstance(tr, dict) and tr.get("result"):
                            tool_results.append(
                                str(tr["result"])[:MAX_TOOL_RESULT_CHARS]
                            )
                    result["summary"]["tool_calls"] += len(data["toolResults"])

                # Extract code chunks
                code_chunks = []
                if data.get("attachedCodeChunks"):
                    for chunk in data["attachedCodeChunks"][
                        :MAX_CODE_CHUNKS_IN_TRANSCRIPT
                    ]:
                        if isinstance(chunk, dict):
                            file_path = chunk.get("filePath", "")
                            code_chunks.append(file_path)
                    result["summary"]["code_changes"] += len(data["attachedCodeChunks"])

                # Find issue keys in text
                if text:
                    for match in issue_pattern.findall(text):
                        all_issue_keys.add(match.upper())

                messages_raw.append(
                    {
                        "bubble_id": bubble_id,
                        "type": msg_role,
                        "text": text[:MAX_MESSAGE_TEXT_CHARS] if text else "",
                        "timestamp": (
                            datetime.fromtimestamp(created_at / 1000).isoformat()
                            if created_at
                            else None
                        ),
                        "tool_results": tool_results if tool_results else None,
                        "code_chunks": code_chunks if code_chunks else None,
                    }
                )

                # Update counts
                if msg_role == "user":
                    result["summary"]["user_messages"] += 1
                elif msg_role == "assistant":
                    result["summary"]["assistant_messages"] += 1

            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.debug(f"Error parsing bubble: {e}")
                continue

        # Sort by timestamp if available, otherwise by bubble_id
        messages_raw.sort(key=lambda x: x.get("timestamp") or x.get("bubble_id") or "")

        # Limit to max_messages
        result["messages"] = messages_raw[:max_messages]
        result["message_count"] = len(messages_raw)
        result["summary"]["issue_keys"] = sorted(all_issue_keys)

        logger.info(
            f"Extracted {len(messages_raw)} messages from chat {chat_id[:8]}..."
        )
        return result

    except subprocess.TimeoutExpired:
        logger.warning("Timeout extracting Cursor chat content")
        return result
    except Exception as e:
        logger.warning(f"Error extracting Cursor chat content: {e}")
        return result


def format_session_context_for_jira(
    chat_content: dict,
    session: "ChatSession | None" = None,
    include_transcript: bool = False,
    max_transcript_chars: int = DEFAULT_MAX_TRANSCRIPT_CHARS,
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
    lines = []

    # Header panel
    lines.append(
        "{panel:title=AI Session Context|borderStyle=solid|borderColor=#0052CC}"
    )

    # Session metadata
    if session:
        lines.append(f"*Session ID:* {session.session_id[:8]}...")
        lines.append(f"*Persona:* {session.persona}")
        if session.project:
            lines.append(f"*Project:* {session.project}")
        if session.branch:
            lines.append(f"*Branch:* {{monospace}}{session.branch}{{monospace}}")
        if session.started_at:
            lines.append(f"*Started:* {session.started_at.strftime('%Y-%m-%d %H:%M')}")
        if session.last_activity:
            duration = session.last_activity - session.started_at
            minutes = int(duration.total_seconds() / 60)
            lines.append(f"*Duration:* ~{minutes} minutes")
        lines.append("")

    # Summary stats
    summary = chat_content.get("summary", {})
    lines.append("h3. Summary")
    lines.append(
        f"* *Messages:* {summary.get('user_messages', 0)} user, {summary.get('assistant_messages', 0)} assistant"
    )
    lines.append(f"* *Tool Calls:* {summary.get('tool_calls', 0)}")
    lines.append(f"* *Code References:* {summary.get('code_changes', 0)}")

    # Related issues
    issue_keys = summary.get("issue_keys", [])
    if issue_keys:
        lines.append(f"* *Related Issues:* {', '.join(issue_keys)}")
    lines.append("")

    # Key actions (extract from messages)
    messages = chat_content.get("messages", [])
    key_actions = []

    for msg in messages:
        if msg.get("type") == "assistant" and msg.get("tool_results"):
            # Extract tool action summaries
            for tr in msg["tool_results"][:3]:
                if tr and len(tr) > 10:
                    # Truncate and clean
                    action = tr[:100].replace("\n", " ").strip()
                    if action:
                        key_actions.append(action)

    if key_actions:
        lines.append("h3. Key Actions")
        for action in key_actions[:10]:  # Limit to 10 actions
            lines.append(f"* {action}")
        lines.append("")

    # Optional transcript
    if include_transcript and messages:
        lines.append("{expand:Full Transcript}")
        lines.append("{code}")

        transcript_chars = 0
        for msg in messages:
            if transcript_chars >= max_transcript_chars:
                lines.append("... (truncated)")
                break

            role = msg.get("type", "unknown").upper()
            text = msg.get("text", "")[:500]  # Truncate individual messages
            timestamp = msg.get("timestamp", "")[:16] if msg.get("timestamp") else ""

            entry = f"[{timestamp}] {role}: {text}\n"
            lines.append(entry)
            transcript_chars += len(entry)

        lines.append("{code}")
        lines.append("{expand}")

    lines.append("{panel}")

    return "\n".join(lines)


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
    import re
    import sqlite3

    # OPTIMIZATION: If no specific chat IDs provided, skip the expensive full scan
    if not chat_ids:
        logger.debug(
            "get_cursor_chat_personas: No chat_ids provided, skipping expensive full scan"
        )
        return {}

    # Valid persona names (from personas/ directory)
    VALID_PERSONAS = {
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

    try:
        global_db = (
            Path.home()
            / ".config"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )
        if not global_db.exists():
            logger.debug("Cursor global storage not found")
            return {}

        # Use Python sqlite3 directly (faster than subprocess)
        # Use context manager to ensure connection is always closed
        # Patterns to detect persona loads (ordered by specificity)
        patterns = [
            # persona_load("developer") or persona_load('developer')
            re.compile(r'persona_load\s*\(\s*["\'](\w+)["\']', re.IGNORECASE),
            # session_start(agent="devops") or agent='devops'
            re.compile(r'agent\s*=\s*["\'](\w+)["\']', re.IGNORECASE),
            # "Loaded persona: developer" or "Switched to persona: developer"
            re.compile(
                r'(?:Loaded|Switched to)\s+persona[:\s]+[`"\']?(\w+)[`"\']?',
                re.IGNORECASE,
            ),
            # "**Persona:** `developer`" (markdown output from session_start)
            re.compile(r"\*\*Persona:\*\*\s*`(\w+)`", re.IGNORECASE),
            # "Persona: developer" (plain text)
            re.compile(r'Persona:\s*[`"\']?(\w+)[`"\']?', re.IGNORECASE),
        ]

        chat_personas: dict[str, list[tuple[int, str]]] = {}

        conn = sqlite3.connect(str(global_db), timeout=10)
        try:
            cursor = conn.cursor()

            for cid in chat_ids:
                try:
                    cursor.execute(
                        """SELECT key, value FROM cursorDiskKV
                           WHERE key LIKE ?
                           AND (value LIKE '%persona%' OR value LIKE '%agent=%' OR value LIKE '%Persona%')
                           LIMIT 50""",
                        (f"bubbleId:{cid}:%",),
                    )

                    for key, value in cursor.fetchall():
                        try:
                            parts = key.split(":")
                            if len(parts) < 3:
                                continue
                            chat_id = parts[1]
                            bubble_id = int(parts[2]) if parts[2].isdigit() else 0

                            data = json.loads(value)
                            text = data.get("text", "")
                            if not text:
                                continue

                            for pattern in patterns:
                                for match in pattern.findall(text):
                                    persona = match.lower()
                                    if persona not in VALID_PERSONAS:
                                        continue
                                    if chat_id not in chat_personas:
                                        chat_personas[chat_id] = []
                                    chat_personas[chat_id].append((bubble_id, persona))

                        except (json.JSONDecodeError, ValueError):
                            continue
                except sqlite3.Error as e:
                    logger.debug(f"Error querying chat {cid} for personas: {e}")
                    continue
        finally:
            conn.close()

        # Return the last (highest bubble_id) persona for each chat
        result_map = {}
        for chat_id, persona_list in chat_personas.items():
            if persona_list:
                persona_list.sort(key=lambda x: x[0])
                last_persona = persona_list[-1][1]
                result_map[chat_id] = last_persona

        if result_map:
            logger.debug(f"Detected personas in {len(result_map)} chat(s) from content")

        return result_map

    except sqlite3.Error as e:
        logger.warning(f"SQLite error scanning for personas: {e}")
        return {}
    except Exception as e:
        logger.warning(f"Error scanning Cursor chats for personas: {e}")
        return {}


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
    import re
    import sqlite3

    # OPTIMIZATION: If no specific chat IDs provided, skip the expensive full scan
    if not chat_ids:
        logger.debug(
            "get_cursor_chat_projects: No chat_ids provided, skipping expensive full scan"
        )
        return {}

    # Load valid project names from config
    try:
        from server.utils import load_config

        config = load_config()
        repos = config.get("repositories", {})
        VALID_PROJECTS = set(repos.keys())
    except (OSError, json.JSONDecodeError, KeyError, ImportError):
        # Fallback to known projects
        VALID_PROJECTS = {
            "automation-analytics-backend",
            "pdf-generator",
            "app-interface",
            "konflux-release-data",
            "redhat-ai-workflow",
        }

    if not VALID_PROJECTS:
        return {}

    try:
        global_db = (
            Path.home()
            / ".config"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )
        if not global_db.exists():
            logger.debug("Cursor global storage not found")
            return {}

        # Use Python sqlite3 directly (faster than subprocess)
        # Use context manager to ensure connection is always closed
        # Build regex patterns for each project
        project_patterns = []
        for proj in VALID_PROJECTS:
            escaped = re.escape(proj)
            project_patterns.append(
                (re.compile(rf'project\s*=\s*["\']({escaped})["\']', re.IGNORECASE), 10)
            )
            project_patterns.append(
                (re.compile(rf"\*\*Project:\*\*\s*`({escaped})`", re.IGNORECASE), 9)
            )
            project_patterns.append(
                (re.compile(rf'Project:\s*[`"\']?({escaped})[`"\']?', re.IGNORECASE), 8)
            )
            project_patterns.append(
                (
                    re.compile(
                        rf"/(?:home|Users)/[^/]+/(?:src|projects?|repos?)/({escaped})/",
                        re.IGNORECASE,
                    ),
                    7,
                )
            )
            project_patterns.append(
                (re.compile(rf'[\w-]+/({escaped})(?:\s|$|["\'\]])', re.IGNORECASE), 6)
            )
            project_patterns.append((re.compile(rf"\b({escaped})\b", re.IGNORECASE), 5))

        chat_projects: dict[str, list[tuple[int, int, str]]] = {}

        conn = sqlite3.connect(str(global_db), timeout=10)
        try:
            cursor = conn.cursor()

            for cid in chat_ids:
                try:
                    cursor.execute(
                        """SELECT key, value FROM cursorDiskKV
                           WHERE key LIKE ?
                           AND (value LIKE '%project=%' OR value LIKE '%Project:%')
                           LIMIT 50""",
                        (f"bubbleId:{cid}:%",),
                    )

                    for key, value in cursor.fetchall():
                        try:
                            parts = key.split(":")
                            if len(parts) < 3:
                                continue
                            chat_id = parts[1]
                            bubble_id = int(parts[2]) if parts[2].isdigit() else 0

                            data = json.loads(value)
                            text = data.get("text", "")
                            if not text:
                                continue

                            for pattern, priority in project_patterns:
                                for match in pattern.findall(text):
                                    project_name = match.lower()
                                    for valid_proj in VALID_PROJECTS:
                                        if valid_proj.lower() == project_name:
                                            project_name = valid_proj
                                            break

                                    if project_name not in VALID_PROJECTS:
                                        continue
                                    if chat_id not in chat_projects:
                                        chat_projects[chat_id] = []
                                    chat_projects[chat_id].append(
                                        (bubble_id, priority, project_name)
                                    )

                        except (json.JSONDecodeError, ValueError):
                            continue
                except sqlite3.Error as e:
                    logger.debug(f"Error querying chat {cid} for projects: {e}")
                    continue
        finally:
            conn.close()

        # Return the best project for each chat
        result_map = {}
        for chat_id, project_list in chat_projects.items():
            if project_list:
                project_list.sort(key=lambda x: (x[1], x[0]), reverse=True)
                best_project = project_list[0][2]
                if best_project != "redhat-ai-workflow":
                    result_map[chat_id] = best_project

        if result_map:
            logger.debug(f"Detected projects in {len(result_map)} chat(s) from content")

        return result_map

    except sqlite3.Error as e:
        logger.warning(f"SQLite error scanning for projects: {e}")
        return {}
    except Exception as e:
        logger.warning(f"Error scanning Cursor chats for projects: {e}")
        return {}


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
        issue_keys: Optional list of issue keys to search for. If None, finds all AAP-XXXXX patterns.

    Returns:
        Dict mapping issue key to list of meeting info dicts:
        {
            "AAP-12345": [
                {"meeting_id": 1, "title": "Sprint Planning", "date": "2025-01-20", "matches": 3},
                ...
            ]
        }
    """
    import re
    import subprocess
    from collections import defaultdict

    try:
        from server.paths import MEETINGS_DB_FILE

        db_path = MEETINGS_DB_FILE
        if not db_path.exists():
            logger.debug("Meet bot database not found")
            return {}

        # Build patterns for flexible matching
        # Pattern 1: Standard AAP-XXXXX (with or without hyphen)
        # Pattern 2: "issue" or "ticket" followed by number
        # Pattern 3: Just "AAP" followed by number (spoken without hyphen)

        # Query all transcript text with meeting info
        query = """
            SELECT t.meeting_id, t.text, m.title, m.scheduled_start
            FROM transcripts t
            JOIN meetings m ON t.meeting_id = m.id
            WHERE m.status = 'completed'
        """

        result = subprocess.run(
            ["sqlite3", "-separator", "|||", str(db_path), query],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.debug(f"Failed to query meet bot DB: {result.stderr}")
            return {}

        # Flexible patterns for spoken issue references
        patterns = [
            # Standard: AAP-12345 or AAP12345 or AAP 12345
            re.compile(r"\bAAP[-\s]?(\d{4,7})\b", re.IGNORECASE),
            # Spoken: "issue 12345" or "issue number 12345"
            re.compile(r"\bissue\s+(?:number\s+)?(\d{4,7})\b", re.IGNORECASE),
            # Spoken: "ticket 12345"
            re.compile(r"\bticket\s+(?:number\s+)?(\d{4,7})\b", re.IGNORECASE),
            # Spoken: "jira 12345"
            re.compile(
                r"\bjira\s+(?:issue\s+)?(?:number\s+)?(\d{4,7})\b", re.IGNORECASE
            ),
        ]

        # Track matches per meeting per issue
        # Structure: {issue_key: {meeting_id: {"title": ..., "date": ..., "count": N}}}
        issue_meetings: dict[str, dict[int, dict]] = defaultdict(
            lambda: defaultdict(lambda: {"title": "", "date": "", "count": 0})
        )

        for line in result.stdout.strip().split("\n"):
            if not line or "|||" not in line:
                continue
            try:
                parts = line.split("|||")
                if len(parts) < 4:
                    continue
                meeting_id = int(parts[0])
                text = parts[1]
                title = parts[2]
                date = parts[3][:10] if parts[3] else ""  # Just the date part

                # Find all issue references in this transcript entry
                found_numbers: set[str] = set()
                for pattern in patterns:
                    for match in pattern.finditer(text):
                        # Extract just the number part
                        number = match.group(1)
                        found_numbers.add(number)

                # Convert to standard AAP-XXXXX format and record
                for number in found_numbers:
                    issue_key = f"AAP-{number}"

                    # If we're filtering to specific keys, check if this matches
                    if issue_keys and issue_key not in issue_keys:
                        continue

                    issue_meetings[issue_key][meeting_id]["title"] = title
                    issue_meetings[issue_key][meeting_id]["date"] = date
                    issue_meetings[issue_key][meeting_id]["count"] += 1

            except (ValueError, IndexError):
                continue

        # Convert to final format
        result_map: dict[str, list[dict]] = {}
        for issue_key, meetings in issue_meetings.items():
            result_map[issue_key] = [
                {
                    "meeting_id": mid,
                    "title": info["title"],
                    "date": info["date"],
                    "matches": info["count"],
                }
                for mid, info in sorted(
                    meetings.items(), key=lambda x: x[1]["date"], reverse=True
                )
            ]

        if result_map:
            logger.info(
                f"Found {len(result_map)} issue(s) mentioned in meeting transcripts"
            )

        return result_map

    except subprocess.TimeoutExpired:
        logger.warning("Timeout scanning meet bot DB for issue keys")
        return {}
    except Exception as e:
        logger.warning(f"Error scanning meeting transcripts for issue keys: {e}")
        return {}


def get_cursor_chat_names(workspace_uri: str) -> dict[str, str]:
    """Get a mapping of Cursor chat IDs to their names.

    Args:
        workspace_uri: The workspace URI

    Returns:
        Dict mapping chat ID to chat name
    """
    chats, _ = list_cursor_chats(workspace_uri)
    return {c["composerId"]: c.get("name") for c in chats if c.get("composerId")}


def inject_context_to_cursor_chat(
    workspace_uri: str,
    chat_id: str | None = None,
    context: dict | None = None,
    system_message: str | None = None,
) -> bool:
    """Inject pre-built context into a Cursor chat.

    This modifies the chat's state in Cursor's SQLite database to include
    initial context that will be loaded when the chat is opened.

    WARNING: This modifies Cursor's internal database. Use with caution.
    The database format may change between Cursor versions.

    Args:
        workspace_uri: The workspace URI (e.g., "file:///home/user/project")
        chat_id: Optional specific chat ID. If None, creates a new chat.
        context: Dict with context to inject (persona, skills, memory, etc.)
        system_message: Optional system message to prepend to the chat

    Returns:
        True if successful, False otherwise
    """
    import subprocess
    import time

    try:
        workspace_storage_dir = _cursor_workspace_storage()

        if not workspace_storage_dir.exists():
            logger.warning("Cursor workspace storage not found")
            return False

        # Find the workspace storage folder
        for storage_dir in workspace_storage_dir.iterdir():
            if not storage_dir.is_dir():
                continue

            workspace_json = storage_dir / "workspace.json"
            if not workspace_json.exists():
                continue

            try:
                workspace_data = json.loads(workspace_json.read_text())
                folder_uri = workspace_data.get("folder", "")

                if folder_uri == workspace_uri:
                    db_path = storage_dir / "state.vscdb"
                    if not db_path.exists():
                        logger.warning(f"Cursor state.vscdb not found at {db_path}")
                        return False

                    # Read current composer data
                    query = "SELECT value FROM ItemTable WHERE key = 'composer.composerData'"
                    result = subprocess.run(
                        ["sqlite3", str(db_path), query],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )

                    if result.returncode != 0:
                        logger.warning(f"Failed to read composer data: {result.stderr}")
                        return False

                    if not result.stdout.strip():
                        # No existing composer data, create new structure
                        composer_data = {
                            "allComposers": [],
                            "lastFocusedComposerIds": [],
                        }
                    else:
                        composer_data = json.loads(result.stdout.strip())

                    # Generate a new chat ID if not provided, or validate provided one
                    import uuid as uuid_module

                    if chat_id is None:
                        chat_id = str(uuid_module.uuid4())
                    else:
                        # Validate chat_id is a valid UUID to prevent SQL injection
                        try:
                            uuid_module.UUID(chat_id)
                        except (ValueError, TypeError):
                            logger.warning(
                                f"Invalid chat_id format (expected UUID): {chat_id[:50] if chat_id else 'None'}"
                            )
                            return False

                    # Build the context message
                    context_text = ""
                    if system_message:
                        context_text += f"{system_message}\n\n"

                    if context:
                        if context.get("persona"):
                            context_text += f"**Persona:** {context['persona']}\n"
                        if context.get("issue_key"):
                            context_text += f"**Issue:** {context['issue_key']}\n"
                        if context.get("skills"):
                            context_text += (
                                f"**Skills:** {', '.join(context['skills'])}\n"
                            )
                        if context.get("memory"):
                            context_text += (
                                f"**Memory:** {', '.join(context['memory'])}\n"
                            )

                    # Create or update the chat entry
                    now_ms = int(time.time() * 1000)
                    new_chat = {
                        "composerId": chat_id,
                        "name": context.get("name") if context else None,
                        "createdAt": now_ms,
                        "lastUpdatedAt": now_ms,
                        "isArchived": False,
                        "isDraft": False,
                        # Note: We can't directly inject messages into the chat history
                        # as that's stored in a separate global database.
                        # Instead, we create a chat entry that will be populated
                        # when the user opens it.
                    }

                    # Check if chat already exists
                    existing_idx = None
                    for i, c in enumerate(composer_data.get("allComposers", [])):
                        if c.get("composerId") == chat_id:
                            existing_idx = i
                            break

                    if existing_idx is not None:
                        composer_data["allComposers"][existing_idx].update(new_chat)
                    else:
                        composer_data["allComposers"].insert(0, new_chat)

                    # Set as the focused chat
                    composer_data["lastFocusedComposerIds"] = [chat_id]

                    # Write back to database
                    # Need to escape the JSON for SQLite
                    json_value = json.dumps(composer_data).replace("'", "''")
                    update_query = f"UPDATE ItemTable SET value = '{json_value}' WHERE key = 'composer.composerData'"

                    result = subprocess.run(
                        ["sqlite3", str(db_path), update_query],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )

                    if result.returncode != 0:
                        logger.warning(
                            f"Failed to update composer data: {result.stderr}"
                        )
                        return False

                    logger.info(f"Injected context into Cursor chat {chat_id}")
                    return True

            except (json.JSONDecodeError, KeyError) as e:
                logger.debug(f"Error processing workspace.json in {storage_dir}: {e}")
                continue

        logger.warning(f"No matching workspace storage found for {workspace_uri}")
        return False

    except Exception as e:
        logger.warning(f"Error injecting context to Cursor chat: {e}")
        return False


__all__ = [
    "DEFAULT_MAX_TRANSCRIPT_CHARS",
    "MAX_CODE_CHUNKS_IN_TRANSCRIPT",
    "MAX_MESSAGE_TEXT_CHARS",
    "MAX_TOOL_RESULT_CHARS",
    "MAX_TOOL_RESULTS_IN_TRANSCRIPT",
    "format_session_context_for_jira",
    "get_cursor_chat_content",
    "get_cursor_chat_id_from_db",
    "get_cursor_chat_ids",
    "get_cursor_chat_info_from_db",
    "get_cursor_chat_issue_keys",
    "get_cursor_chat_names",
    "get_cursor_chat_personas",
    "get_cursor_chat_projects",
    "get_meeting_transcript_issue_keys",
    "inject_context_to_cursor_chat",
    "list_cursor_chats",
]
