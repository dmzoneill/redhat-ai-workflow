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
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import Context

logger = logging.getLogger(__name__)

# Default workspace key when list_roots() is unavailable
DEFAULT_WORKSPACE = "default"

# Default project when none detected
DEFAULT_PROJECT = "redhat-ai-workflow"


def get_default_persona() -> str:
    """Get the default persona from config, with fallback to 'researcher'.

    This centralizes the default persona logic so it can be changed in one place.
    Reads from config.json agent.default_persona setting.
    """
    try:
        from server.utils import load_config

        cfg = load_config()
        return cfg.get("agent", {}).get("default_persona", "researcher")
    except Exception:
        return "researcher"


# Session stale timeout (hours) - sessions inactive for longer are cleaned up
SESSION_STALE_HOURS = 24

# Maximum entries in tool_filter_cache per session to prevent memory leaks
MAX_FILTER_CACHE_SIZE = 50

# Persistence file location - centralized in server.paths
from server.paths import AA_CONFIG_DIR, WORKSPACE_STATES_FILE  # noqa: E402

PERSIST_DIR = AA_CONFIG_DIR
PERSIST_FILE = WORKSPACE_STATES_FILE

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
        workspace_storage_dir = (
            Path.home() / ".config" / "Cursor" / "User" / "workspaceStorage"
        )

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
                    result = subprocess.run(
                        ["sqlite3", str(db_path), query],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )

                    if result.returncode != 0 or not result.stdout.strip():
                        logger.debug(f"No composer data in {db_path}")
                        return None, None

                    composer_data = json.loads(result.stdout.strip())
                    all_composers = composer_data.get("allComposers", [])

                    if not all_composers:
                        logger.debug("No composers found in database")
                        return None, None

                    # Filter out archived/draft chats and sort by lastUpdatedAt
                    active_chats = [
                        c
                        for c in all_composers
                        if not c.get("isArchived") and not c.get("isDraft")
                    ]

                    if not active_chats:
                        logger.debug("No active chats found")
                        return None, None

                    # Get the most recently updated chat (likely the current one)
                    most_recent = max(
                        active_chats, key=lambda x: x.get("lastUpdatedAt", 0)
                    )
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
    import subprocess

    try:
        workspace_storage_dir = (
            Path.home() / ".config" / "Cursor" / "User" / "workspaceStorage"
        )

        if not workspace_storage_dir.exists():
            return [], None

        # Aggregate chats from all matching storage directories
        all_chats: dict[str, dict] = {}  # composerId -> chat dict (dedup by ID)
        active_chat_id = None

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
                    result = subprocess.run(
                        ["sqlite3", str(db_path), query],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )

                    if result.returncode != 0 or not result.stdout.strip():
                        continue  # Try other storage directories

                    composer_data = json.loads(result.stdout.strip())
                    all_composers = composer_data.get("allComposers", [])

                    # Get the active/focused chat ID (use most recent if multiple dirs)
                    last_focused = composer_data.get("lastFocusedComposerIds", [])
                    if last_focused and not active_chat_id:
                        active_chat_id = last_focused[0]

                    # Add chats to aggregated dict, keeping newer versions
                    for c in all_composers:
                        if c.get("isArchived") or c.get("isDraft"):
                            continue
                        # Exclude ghost chats: no name AND no lastUpdatedAt (never actually used)
                        if c.get("name") is None and c.get("lastUpdatedAt") is None:
                            continue

                        composer_id = c.get("composerId")
                        if not composer_id:
                            continue

                        chat_dict = {
                            "composerId": composer_id,
                            "name": c.get("name"),  # Keep None if not set
                            "createdAt": c.get("createdAt", 0),
                            "lastUpdatedAt": c.get("lastUpdatedAt", 0),
                            "isArchived": c.get("isArchived", False),
                            "isDraft": c.get("isDraft", False),
                        }

                        # Keep the chat with the most recent lastUpdatedAt
                        if (
                            composer_id not in all_chats
                            or chat_dict["lastUpdatedAt"]
                            > all_chats[composer_id]["lastUpdatedAt"]
                        ):
                            all_chats[composer_id] = chat_dict

            except (json.JSONDecodeError, KeyError):
                continue

        # Return sorted list
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

        # Use Python sqlite3 directly (faster than subprocess)
        # Use context manager to ensure connection is always closed
        chat_issue_sets: dict[str, set[str]] = {}
        issue_pattern = re.compile(r"AAP-\d{4,7}", re.IGNORECASE)

        with sqlite3.connect(str(global_db), timeout=10) as conn:
            cursor = conn.cursor()

            # Query each chat ID separately to avoid huge result sets
            for cid in chat_ids:
                try:
                    # Query for this specific chat's messages containing AAP-
                    cursor.execute(
                        "SELECT key, value FROM cursorDiskKV WHERE key LIKE ? AND value LIKE '%AAP-%' LIMIT 100",
                        (f"bubbleId:{cid}:%",),
                    )

                    for key, value in cursor.fetchall():
                        try:
                            # Extract chat ID from key: bubbleId:<chatId>:<bubbleId>
                            parts = key.split(":")
                            if len(parts) >= 2:
                                chat_id = parts[1]
                                data = json.loads(value)
                                text = data.get("text", "")
                                if text:
                                    matches = issue_pattern.findall(text)
                                    if matches:
                                        if chat_id not in chat_issue_sets:
                                            chat_issue_sets[chat_id] = set()
                                        for m in matches:
                                            chat_issue_sets[chat_id].add(m.upper())
                        except (json.JSONDecodeError, ValueError):
                            continue
                except sqlite3.Error as e:
                    logger.debug(f"Error querying chat {cid}: {e}")
                    continue

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
                    for tr in data["toolResults"][:5]:  # Limit tool results
                        if isinstance(tr, dict) and tr.get("result"):
                            tool_results.append(str(tr["result"])[:200])
                    result["summary"]["tool_calls"] += len(data["toolResults"])

                # Extract code chunks
                code_chunks = []
                if data.get("attachedCodeChunks"):
                    for chunk in data["attachedCodeChunks"][:3]:
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
                        "text": text[:2000] if text else "",  # Truncate long messages
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

        # Collect all persona mentions per chat with their position (to find last one)
        chat_personas: dict[str, list[tuple[int, str]]] = {}

        with sqlite3.connect(str(global_db), timeout=10) as conn:
            cursor = conn.cursor()

            # Query each chat ID separately
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
                            if len(parts) >= 3:
                                chat_id = parts[1]
                                try:
                                    bubble_id = (
                                        int(parts[2]) if parts[2].isdigit() else 0
                                    )
                                except (ValueError, IndexError):
                                    bubble_id = 0

                                data = json.loads(value)
                                text = data.get("text", "")
                                if not text:
                                    continue

                                for pattern in patterns:
                                    matches = pattern.findall(text)
                                    for match in matches:
                                        persona = match.lower()
                                        if persona in VALID_PERSONAS:
                                            if chat_id not in chat_personas:
                                                chat_personas[chat_id] = []
                                            chat_personas[chat_id].append(
                                                (bubble_id, persona)
                                            )

                        except (json.JSONDecodeError, ValueError):
                            continue
                except sqlite3.Error as e:
                    logger.debug(f"Error querying chat {cid} for personas: {e}")
                    continue

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
    except Exception:
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

        # Collect all project mentions per chat
        chat_projects: dict[str, list[tuple[int, int, str]]] = {}

        with sqlite3.connect(str(global_db), timeout=10) as conn:
            cursor = conn.cursor()

            # Query each chat ID separately
            for cid in chat_ids:
                try:
                    # Build a simple query for this chat - check for project-related content
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
                            if len(parts) >= 3:
                                chat_id = parts[1]
                                try:
                                    bubble_id = (
                                        int(parts[2]) if parts[2].isdigit() else 0
                                    )
                                except (ValueError, IndexError):
                                    bubble_id = 0

                                data = json.loads(value)
                                text = data.get("text", "")
                                if not text:
                                    continue

                                for pattern, priority in project_patterns:
                                    matches = pattern.findall(text)
                                    for match in matches:
                                        project_name = match.lower()
                                        for valid_proj in VALID_PROJECTS:
                                            if valid_proj.lower() == project_name:
                                                project_name = valid_proj
                                                break

                                        if project_name in VALID_PROJECTS:
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
        workspace_storage_dir = (
            Path.home() / ".config" / "Cursor" / "User" / "workspaceStorage"
        )

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


@dataclass
class ChatSession:
    """State for a single chat session within a workspace.

    Each chat session maintains its own:
    - Session ID (generated on session_start())
    - Project (per-session, not per-workspace!)
    - Persona (developer, devops, incident, release)
    - Active issue and branch
    - Tool filter cache (for NPU results)

    Tool Counts:
    - static_tool_count: Baseline count from persona YAML (all tools available)
    - dynamic_tool_count: Context-aware count from NPU filter (tools for current message)
    - tool_count: Computed property returning dynamic if > 0, else static
    """

    session_id: str
    workspace_uri: str
    persona: str = field(default_factory=get_default_persona)
    project: str | None = (
        None  # Per-session project (can differ from workspace default)
    )
    is_project_auto_detected: bool = (
        False  # True if project was auto-detected from workspace path
    )
    issue_key: str | None = None
    branch: str | None = None

    # Dual tool count system
    static_tool_count: int = (
        0  # Baseline from persona YAML (calculated from tool modules)
    )
    dynamic_tool_count: int = (
        0  # Context-aware from NPU filter (updated on each filter call)
    )
    last_filter_message: str | None = None  # Message that triggered last NPU filter
    last_filter_time: datetime | None = None  # When last NPU filter was run

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

    # Meeting transcript references (meetings where session's issues were discussed)
    # Format: [{"meeting_id": 1, "title": "Sprint Planning", "date": "2025-01-20", "matches": 3}, ...]
    meeting_references: list[dict] = field(default_factory=list)

    # Memory abstraction caches (per-session to avoid cross-chat interference)
    # Intent classification cache: {query_hash: IntentClassification}
    intent_cache: dict[str, dict] = field(default_factory=dict)
    # Memory query cache: {query_hash: QueryResult}
    memory_query_cache: dict[str, dict] = field(default_factory=dict)

    @property
    def tool_count(self) -> int:
        """Computed tool count: dynamic if available, else static.

        Returns dynamic_tool_count if > 0 (context-aware from NPU filter),
        otherwise returns static_tool_count (baseline from persona YAML).
        """
        return (
            self.dynamic_tool_count
            if self.dynamic_tool_count > 0
            else self.static_tool_count
        )

    # Backward compatibility property
    @property
    def active_tools(self) -> set[str]:
        """Deprecated: Use tool_count instead. Returns empty set for compatibility."""
        return set()

    @active_tools.setter
    def active_tools(self, value: set[str]) -> None:
        """Deprecated: Sets static_tool_count from the length of the provided set."""
        self.static_tool_count = len(value) if value else 0

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
            # Dual tool counts
            "static_tool_count": self.static_tool_count,
            "dynamic_tool_count": self.dynamic_tool_count,
            "tool_count": self.tool_count,  # Computed for backward compat
            "last_filter_message": self.last_filter_message,
            "last_filter_time": (
                self.last_filter_time.isoformat() if self.last_filter_time else None
            ),
            # Timestamps
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_activity": (
                self.last_activity.isoformat() if self.last_activity else None
            ),
            "name": self.name,
            "last_tool": self.last_tool,
            "last_tool_time": (
                self.last_tool_time.isoformat() if self.last_tool_time else None
            ),
            "tool_call_count": self.tool_call_count,
            "meeting_references": self.meeting_references,
        }

    def clear_filter_cache(self) -> None:
        """Clear the tool filter cache (e.g., when persona changes)."""
        self.tool_filter_cache.clear()

    def add_to_filter_cache(self, key: str, tools: list[str]) -> None:
        """Add an entry to the filter cache with size limiting.

        Prevents unbounded memory growth by evicting oldest entries when
        cache exceeds MAX_FILTER_CACHE_SIZE.

        Args:
            key: Cache key (typically message hash)
            tools: List of tool names to cache
        """
        # Evict oldest entries if cache is full
        while len(self.tool_filter_cache) >= MAX_FILTER_CACHE_SIZE:
            # Remove first (oldest) entry - dict maintains insertion order in Python 3.7+
            oldest_key = next(iter(self.tool_filter_cache))
            del self.tool_filter_cache[oldest_key]

        self.tool_filter_cache[key] = tools

    # ==================== Memory Abstraction Cache Methods ====================

    MAX_INTENT_CACHE_SIZE = 100
    MAX_QUERY_CACHE_SIZE = 50

    def cache_intent(self, query_hash: str, intent: dict) -> None:
        """Cache an intent classification result.

        Args:
            query_hash: Hash of the query
            intent: IntentClassification as dict
        """
        # Evict oldest entries if cache is full
        while len(self.intent_cache) >= self.MAX_INTENT_CACHE_SIZE:
            oldest_key = next(iter(self.intent_cache))
            del self.intent_cache[oldest_key]

        self.intent_cache[query_hash] = intent

    def get_cached_intent(self, query_hash: str) -> dict | None:
        """Get a cached intent classification.

        Args:
            query_hash: Hash of the query

        Returns:
            Cached IntentClassification as dict, or None if not cached
        """
        return self.intent_cache.get(query_hash)

    def cache_memory_query(self, query_hash: str, result: dict) -> None:
        """Cache a memory query result.

        Args:
            query_hash: Hash of the query
            result: QueryResult as dict
        """
        # Evict oldest entries if cache is full
        while len(self.memory_query_cache) >= self.MAX_QUERY_CACHE_SIZE:
            oldest_key = next(iter(self.memory_query_cache))
            del self.memory_query_cache[oldest_key]

        self.memory_query_cache[query_hash] = result

    def get_cached_memory_query(self, query_hash: str) -> dict | None:
        """Get a cached memory query result.

        Args:
            query_hash: Hash of the query

        Returns:
            Cached QueryResult as dict, or None if not cached
        """
        return self.memory_query_cache.get(query_hash)

    def clear_memory_caches(self) -> None:
        """Clear all memory-related caches."""
        self.intent_cache.clear()
        self.memory_query_cache.clear()


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
        # Try to get Cursor's chat UUID and name if no session_id provided
        cursor_chat_name = None
        if session_id is None:
            cursor_chat_id, cursor_chat_name = get_cursor_chat_info_from_db(
                self.workspace_uri
            )
            if cursor_chat_id:
                session_id = cursor_chat_id
                logger.info(
                    f"Using Cursor chat ID as session ID: {session_id} ({cursor_chat_name})"
                )
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
        session_auto_detected = (
            is_project_auto_detected if project is not None else self.is_auto_detected
        )

        # Use default persona from config if not specified
        session_persona = persona if persona is not None else get_default_persona()

        session = ChatSession(
            session_id=session_id,
            workspace_uri=self.workspace_uri,
            persona=session_persona,
            project=session_project,
            is_project_auto_detected=session_auto_detected,
            static_tool_count=tool_count,
            name=name,
        )

        self.sessions[session_id] = session
        self.active_session_id = session_id
        self.touch()

        logger.info(
            f"Created session {session_id} in workspace {self.workspace_uri} with project '{session_project}'"
        )

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
            # Refresh static tool count if zero (e.g., after restore from disk)
            if session and refresh_tools and session.static_tool_count == 0:
                session.static_tool_count = len(self._get_loaded_tools())
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
        if session_id in self.sessions:
            del self.sessions[session_id]
            if self.active_session_id == session_id:
                # Set active to most recent remaining session
                if self.sessions:
                    most_recent = max(
                        self.sessions.values(), key=lambda s: s.last_activity
                    )
                    self.active_session_id = most_recent.session_id
                else:
                    self.active_session_id = None
            logger.info(
                f"Removed session {session_id} from workspace {self.workspace_uri}"
            )

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
            logger.info(
                f"Cleaned up {len(stale_ids)} stale session(s) not in Cursor DB from {self.workspace_uri}"
            )

        return len(stale_ids)

    def session_count(self) -> int:
        """Get number of sessions in this workspace."""
        return len(self.sessions)

    def sync_with_cursor_db(  # noqa: C901
        self, session_ids: list[str] | None = None, skip_content_scan: bool = False
    ) -> dict:
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
        cursor_chats, cursor_active_id = list_cursor_chats(self.workspace_uri)
        cursor_chat_map = {c["composerId"]: c for c in cursor_chats}
        cursor_ids = set(cursor_chat_map.keys())
        our_ids = set(self.sessions.keys())

        result = {"added": 0, "removed": 0, "renamed": 0, "updated": 0}

        # Update active session from Cursor's lastFocusedComposerIds
        if cursor_active_id and cursor_active_id in cursor_ids:
            if self.active_session_id != cursor_active_id:
                logger.info(f"Updating active session from Cursor: {cursor_active_id}")
                self.active_session_id = cursor_active_id

        # Get currently loaded tools count (for active session)
        current_tool_count = len(self._get_loaded_tools())

        # Determine which sessions to scan for content (expensive operations)
        # If session_ids provided, only scan those; if skip_content_scan, scan none
        if skip_content_scan:
            scan_ids = []
        elif session_ids:
            scan_ids = list(session_ids)
        else:
            scan_ids = []  # Default to no content scanning - too expensive

        # Extract all issue keys from chat names and content
        # Pattern: AAP-XXXXX (4-7 digits, case insensitive)
        import re

        issue_pattern = re.compile(r"AAP-\d{4,7}", re.IGNORECASE)

        # First pass: extract all issue keys from chat names (cheap, do for all)
        issue_keys_from_names: dict[str, set[str]] = {}
        for sid, chat in cursor_chat_map.items():
            name = chat.get("name") or ""
            matches = issue_pattern.findall(name)
            if matches:
                issue_keys_from_names[sid] = {m.upper() for m in matches}

        # Expensive content scanning - only for target sessions
        # These query the 7GB global Cursor database
        issue_keys_from_content: dict[str, str] = {}
        personas_from_content: dict[str, str] = {}
        projects_from_content: dict[str, str] = {}

        if scan_ids:
            # Second pass: scan chat content for issue keys (expensive)
            issue_keys_from_content = get_cursor_chat_issue_keys(scan_ids)

            # Third pass: scan chat content for persona loads (expensive)
            personas_from_content = get_cursor_chat_personas(scan_ids)

            # Fourth pass: scan chat content for project mentions (expensive)
            projects_from_content = get_cursor_chat_projects(scan_ids)

        # Merge: combine keys from name and content, deduplicate and sort
        issue_keys: dict[str, str] = {}
        for sid in cursor_ids:
            all_keys: set[str] = set()
            # Add keys from name
            if sid in issue_keys_from_names:
                all_keys.update(issue_keys_from_names[sid])
            # Add keys from content (already comma-separated string)
            if sid in issue_keys_from_content:
                content_keys = [
                    k.strip() for k in issue_keys_from_content[sid].split(",")
                ]
                all_keys.update(content_keys)

            if all_keys:
                # Sort by numeric part and join
                sorted_keys = sorted(all_keys, key=lambda x: int(x.split("-")[1]))
                issue_keys[sid] = ", ".join(sorted_keys)

        # 1. Remove sessions that no longer exist in Cursor
        removed_ids = our_ids - cursor_ids
        for sid in removed_ids:
            logger.info(f"Removing session {sid} - no longer in Cursor DB")
            del self.sessions[sid]
            result["removed"] += 1
            # Update active session if needed
            if self.active_session_id == sid:
                self.active_session_id = None

        # 2. Add sessions that exist in Cursor but not in our system
        # (These are chats the user created but never called session_start())
        # We create minimal session entries for them
        added_ids = cursor_ids - our_ids
        for sid in added_ids:
            cursor_chat = cursor_chat_map[sid]
            logger.info(
                f"Adding session {sid} from Cursor DB: {cursor_chat.get('name')}"
            )

            # Convert Cursor's lastUpdatedAt (ms timestamp) to datetime
            last_updated = None
            if cursor_chat.get("lastUpdatedAt"):
                last_updated = datetime.fromtimestamp(
                    cursor_chat["lastUpdatedAt"] / 1000
                )

            # Use detected persona from chat content if available, otherwise default
            detected_persona = personas_from_content.get(sid)
            session_persona = detected_persona or get_default_persona()
            if detected_persona:
                logger.info(
                    f"Detected persona '{detected_persona}' from chat content for {sid}"
                )

            # Use detected project from chat content if available, otherwise workspace default
            detected_project = projects_from_content.get(sid)
            session_project = detected_project or self.project
            is_project_auto = detected_project is None and self.is_auto_detected
            if detected_project:
                logger.info(
                    f"Detected project '{detected_project}' from chat content for {sid}"
                )

            session = ChatSession(
                session_id=sid,
                workspace_uri=self.workspace_uri,
                persona=session_persona,
                project=session_project,
                is_project_auto_detected=is_project_auto,
                name=cursor_chat.get("name"),
                static_tool_count=get_persona_tool_count(session_persona),
                issue_key=issue_keys.get(sid),  # Set issue key if found in chat
            )
            if last_updated:
                session.last_activity = last_updated
                session.started_at = datetime.fromtimestamp(
                    cursor_chat.get("createdAt", cursor_chat["lastUpdatedAt"]) / 1000
                )
            self.sessions[sid] = session
            result["added"] += 1

        # 3. Update existing sessions (names, last_activity, tool_count, issue_key)
        for sid in our_ids & cursor_ids:
            cursor_chat = cursor_chat_map[sid]
            session = self.sessions[sid]
            updated = False

            # Update name if Cursor has one and it's different
            cursor_name = cursor_chat.get("name")
            if cursor_name and cursor_name != session.name:
                logger.debug(
                    f"Renaming session {sid}: '{session.name}' -> '{cursor_name}'"
                )
                session.name = cursor_name
                result["renamed"] += 1
            # Clear "unnamed" placeholder so UI uses better fallback
            elif not cursor_name and session.name == "unnamed":
                session.name = None
                result["renamed"] += 1

            # Update last_activity from Cursor's lastUpdatedAt
            if cursor_chat.get("lastUpdatedAt"):
                cursor_last_activity = datetime.fromtimestamp(
                    cursor_chat["lastUpdatedAt"] / 1000
                )
                if (
                    session.last_activity is None
                    or cursor_last_activity > session.last_activity
                ):
                    session.last_activity = cursor_last_activity
                    updated = True

            # Update static_tool_count
            # - For active session: use currently loaded tools
            # - For inactive sessions: use cached persona tool count if current is 0
            is_active = sid == self.active_session_id
            if is_active and current_tool_count > 0:
                if session.static_tool_count != current_tool_count:
                    session.static_tool_count = current_tool_count
                    updated = True
            elif session.static_tool_count == 0:
                # Get from persona cache
                persona_count = get_persona_tool_count(session.persona)
                if persona_count > 0:
                    session.static_tool_count = persona_count
                    updated = True

            # Update issue_key if not already set and found in chat content
            if not session.issue_key and sid in issue_keys:
                session.issue_key = issue_keys[sid]
                logger.info(f"Found issue key {issue_keys[sid]} in chat {sid}")
                updated = True

            # Update persona from chat content if session has a generic/default persona
            # This is a backup detection for sessions that didn't persist their persona
            # We update if the session has:
            # - The default persona (e.g., "researcher")
            # - The "workspace" persona (generic fallback)
            default_persona = get_default_persona()
            generic_personas = {default_persona, "workspace"}
            if session.persona in generic_personas and sid in personas_from_content:
                detected_persona = personas_from_content[sid]
                if detected_persona not in generic_personas:
                    logger.info(
                        f"Updating persona for {sid} from chat content: "
                        f"'{session.persona}' -> '{detected_persona}'"
                    )
                    session.persona = detected_persona
                    # Update tool count for new persona
                    new_tool_count = get_persona_tool_count(detected_persona)
                    if new_tool_count > 0:
                        session.static_tool_count = new_tool_count
                    updated = True

            # Update project from chat content if session has auto-detected (workspace default) project
            # Only update if we detected a more specific project than the workspace default
            if session.is_project_auto_detected and sid in projects_from_content:
                detected_project = projects_from_content[sid]
                if detected_project and detected_project != session.project:
                    logger.info(
                        f"Updating project for {sid} from chat content: "
                        f"'{session.project}' -> '{detected_project}'"
                    )
                    session.project = detected_project
                    session.is_project_auto_detected = False  # Now explicitly detected
                    updated = True

            if updated:
                result["updated"] += 1

        # 4. Scan meeting transcripts for issue key mentions
        # Collect all unique issue keys from all sessions
        all_issue_keys: set[str] = set()
        for session in self.sessions.values():
            if session.issue_key:
                for key in session.issue_key.split(", "):
                    all_issue_keys.add(key.strip())

        if all_issue_keys:
            # Get meeting references for all issue keys
            meeting_refs = get_meeting_transcript_issue_keys(list(all_issue_keys))

            # Update each session's meeting_references based on its issue keys
            for session in self.sessions.values():
                if session.issue_key:
                    session_keys = [k.strip() for k in session.issue_key.split(", ")]
                    # Collect all meetings that mention any of this session's issue keys
                    all_meetings: dict[int, dict] = {}  # meeting_id -> meeting info
                    for key in session_keys:
                        if key in meeting_refs:
                            for meeting in meeting_refs[key]:
                                mid = meeting["meeting_id"]
                                if mid not in all_meetings:
                                    all_meetings[mid] = meeting.copy()
                                else:
                                    # Aggregate match counts
                                    all_meetings[mid]["matches"] += meeting["matches"]

                    # Sort by date (most recent first) and update
                    new_refs = sorted(
                        all_meetings.values(),
                        key=lambda x: x.get("date", ""),
                        reverse=True,
                    )
                    if new_refs != session.meeting_references:
                        session.meeting_references = new_refs
                        if new_refs:
                            logger.debug(
                                f"Session {session.session_id[:8]} has {len(new_refs)} meeting reference(s)"
                            )

        total_changes = sum(result.values())
        if total_changes > 0:
            logger.info(
                f"Synced with Cursor DB for {self.workspace_uri}: "
                f"+{result['added']} -{result['removed']} ~{result['renamed']} ↻{result['updated']}"
            )

        return result

    # Keep old name as alias for backward compatibility
    def sync_session_names_from_cursor(self) -> int:
        """Deprecated: Use sync_with_cursor_db() instead."""
        result = self.sync_with_cursor_db()
        return result["renamed"]

    def _get_loaded_tools(self) -> set[str]:
        """Get currently loaded tool names from PersonaLoader."""
        try:
            from .persona_loader import get_loader

            loader = get_loader()
            if loader:
                # Get actual tool names, not module names
                tools = set(loader._tool_to_module.keys())
                logger.info(
                    f"_get_loaded_tools: found {len(tools)} tools from {len(loader.loaded_modules)} modules"
                )
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
            "last_activity": (
                self.last_activity.isoformat() if self.last_activity else None
            ),
        }

    # Backward compatibility properties - delegate to active session
    @property
    def persona(self) -> str:
        """Get persona from active session (backward compat)."""
        session = self.get_active_session()
        return session.persona if session else get_default_persona()

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
    _access_count: int = 0  # Counter for periodic cleanup
    _CLEANUP_INTERVAL: int = 100  # Run cleanup every N accesses

    @classmethod
    async def get_for_ctx(
        cls, ctx: "Context", ensure_session: bool = True
    ) -> WorkspaceState:
        """Get or create workspace state from MCP context.

        Args:
            ctx: MCP Context from tool call
            ensure_session: If True, auto-create a session if none exists

        Returns:
            WorkspaceState for the current workspace
        """
        logger.debug(
            f"get_for_ctx called, current registry has {len(cls._workspaces)} workspace(s)"
        )

        # Periodic cleanup to prevent memory leaks
        cls._access_count += 1
        if cls._access_count >= cls._CLEANUP_INTERVAL:
            cls._access_count = 0
            cleaned = cls.cleanup_stale(max_age_hours=SESSION_STALE_HOURS)
            if cleaned > 0:
                logger.info(f"Periodic cleanup: removed {cleaned} stale workspace(s)")

        workspace_uri = await cls._get_workspace_uri(ctx)
        logger.debug(f"Resolved workspace_uri: {workspace_uri}")

        is_new_workspace = workspace_uri not in cls._workspaces

        if is_new_workspace:
            # Try to restore from disk first (in case server restarted)
            # This handles the case where restore_if_empty was called but
            # the workspace URI didn't match any persisted workspaces
            cls._try_restore_workspace_from_disk(workspace_uri)

            # Check again after potential restore
            if workspace_uri in cls._workspaces:
                logger.info(f"Restored workspace {workspace_uri} from disk")
                is_new_workspace = False
            else:
                # Create new workspace state
                state = WorkspaceState(workspace_uri=workspace_uri)

                # Auto-detect project from workspace path
                detected_project = cls._detect_project(workspace_uri)
                if detected_project:
                    state.project = detected_project
                    state.is_auto_detected = True
                    logger.info(
                        f"Auto-detected project '{detected_project}' for workspace {workspace_uri}"
                    )

                cls._workspaces[workspace_uri] = state
                logger.info(
                    f"Created new workspace state for {workspace_uri}, "
                    f"registry now has {len(cls._workspaces)} workspace(s)"
                )
        else:
            logger.debug(f"Found existing workspace state for {workspace_uri}")
            cls._workspaces[workspace_uri].touch()

        workspace = cls._workspaces[workspace_uri]

        # Auto-create session if none exists and ensure_session is True
        if ensure_session and not workspace.get_active_session():
            logger.info(
                f"No active session in workspace {workspace_uri}, auto-creating one"
            )
            session = workspace.create_session(name="Auto-created")
            logger.info(
                f"Auto-created session {session.session_id} for workspace {workspace_uri}"
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
        for project_name, project_config in repositories.items():
            project_path_str = project_config.get("path", "")
            if not project_path_str:
                continue

            try:
                project_path = Path(project_path_str).expanduser().resolve()
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
                    workspace.last_activity = datetime.fromisoformat(
                        ws_data["last_activity"]
                    )
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
                    persona=sess_data.get("persona", get_default_persona()),
                    project=session_project,
                    is_project_auto_detected=session_auto_detected,
                    issue_key=sess_data.get("issue_key"),
                    branch=sess_data.get("branch"),
                    name=sess_data.get("name"),
                )

                # Parse session timestamps
                if sess_data.get("started_at"):
                    try:
                        session.started_at = datetime.fromisoformat(
                            sess_data["started_at"]
                        )
                    except (ValueError, TypeError):
                        pass

                if sess_data.get("last_activity"):
                    try:
                        session.last_activity = datetime.fromisoformat(
                            sess_data["last_activity"]
                        )
                    except (ValueError, TypeError):
                        pass

                # Restore dual tool counts (new format) or derive from old format
                if sess_data.get("static_tool_count"):
                    session.static_tool_count = sess_data["static_tool_count"]
                elif sess_data.get("tool_count"):
                    # Old format: tool_count was the static count
                    session.static_tool_count = sess_data["tool_count"]
                elif sess_data.get("active_tools"):
                    session.static_tool_count = len(sess_data["active_tools"])

                session.dynamic_tool_count = sess_data.get("dynamic_tool_count", 0)
                session.last_filter_message = sess_data.get("last_filter_message")
                if sess_data.get("last_filter_time"):
                    try:
                        session.last_filter_time = datetime.fromisoformat(
                            sess_data["last_filter_time"]
                        )
                    except (ValueError, TypeError):
                        pass

                # Restore activity tracking
                session.last_tool = sess_data.get("last_tool")
                if sess_data.get("last_tool_time"):
                    try:
                        session.last_tool_time = datetime.fromisoformat(
                            sess_data["last_tool_time"]
                        )
                    except (ValueError, TypeError):
                        pass
                session.tool_call_count = sess_data.get("tool_call_count", 0)
                session.meeting_references = sess_data.get("meeting_references", [])

                workspace.sessions[session_id] = session

            # Add to registry
            cls._workspaces[workspace_uri] = workspace
            logger.info(
                f"Restored workspace {workspace_uri} with {len(workspace.sessions)} session(s) from disk"
            )
            return True

        except Exception as e:
            logger.warning(
                f"Failed to restore workspace {workspace_uri} from disk: {e}"
            )
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
    def get_or_create(
        cls, workspace_uri: str, ensure_session: bool = True
    ) -> WorkspaceState:
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
            logger.info(
                f"No active session in workspace {workspace_uri}, auto-creating one"
            )
            session = workspace.create_session(name="Auto-created")
            logger.info(
                f"Auto-created session {session.session_id} for workspace {workspace_uri}"
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
                f"Synced all workspaces with Cursor DB: "
                f"+{totals['added']} -{totals['removed']} ~{totals['renamed']} ↻{totals['updated']}"
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
            workspace = cls._workspaces.get(workspace_uri)
            if workspace:
                result = workspace.sync_with_cursor_db(session_ids=list(target_ids))
                totals["added"] += result["added"]
                totals["removed"] += result["removed"]
                totals["renamed"] += result["renamed"]
                totals["updated"] += result.get("updated", 0)

        total_changes = sum(totals.values())
        if total_changes > 0:
            logger.debug(
                f"Synced {len(session_ids)} sessions with Cursor DB: "
                f"+{totals['added']} -{totals['removed']} ~{totals['renamed']} ↻{totals['updated']}"
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
            total_sessions = sum(
                len(ws.get("sessions", {})) for ws in all_workspaces.values()
            )
            logger.info(
                f"save_to_disk: saving {len(all_workspaces)} workspace(s) with {total_sessions} session(s)"
            )
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
    def load_from_disk(cls) -> int:  # noqa: C901
        """Restore workspace states from disk.

        Called on server startup to restore sessions from previous run.

        Returns:
            Number of sessions restored.
        """
        if not PERSIST_FILE.exists():
            logger.debug("load_from_disk: No persisted workspace state found")
            return 0

        logger.debug(f"load_from_disk: Loading from {PERSIST_FILE}")

        try:
            with open(PERSIST_FILE) as f:
                data = json.load(f)

            logger.info(
                f"load_from_disk: File contains {len(data.get('workspaces', {}))} workspace(s)"
            )

            version = data.get("version", 1)
            if version < 2:
                logger.warning(
                    f"Old persist format version {version}, skipping restore"
                )
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

                # Parse timestamps
                if ws_data.get("created_at"):
                    try:
                        workspace.created_at = datetime.fromisoformat(
                            ws_data["created_at"]
                        )
                    except (ValueError, TypeError):
                        pass

                if ws_data.get("last_activity"):
                    try:
                        workspace.last_activity = datetime.fromisoformat(
                            ws_data["last_activity"]
                        )
                    except (ValueError, TypeError):
                        pass

                # Restore sessions (inside the for loop, per workspace)
                sessions_data = ws_data.get("sessions", {})
                for session_id, sess_data in sessions_data.items():
                    # Get session's project - use persisted value or fall back to workspace project
                    session_project = sess_data.get("project")
                    session_auto_detected = sess_data.get(
                        "is_project_auto_detected", False
                    )

                    # If session has no project, inherit from workspace (for backward compat)
                    if session_project is None:
                        session_project = workspace.project
                        session_auto_detected = workspace.is_auto_detected

                    session = ChatSession(
                        session_id=session_id,
                        workspace_uri=workspace_uri,
                        persona=sess_data.get("persona", get_default_persona()),
                        project=session_project,
                        is_project_auto_detected=session_auto_detected,
                        issue_key=sess_data.get("issue_key"),
                        branch=sess_data.get("branch"),
                        name=sess_data.get("name"),
                    )

                    # Parse session timestamps
                    if sess_data.get("started_at"):
                        try:
                            session.started_at = datetime.fromisoformat(
                                sess_data["started_at"]
                            )
                        except (ValueError, TypeError):
                            # Keep the default (datetime.now()) if parsing fails
                            pass

                    if sess_data.get("last_activity"):
                        try:
                            session.last_activity = datetime.fromisoformat(
                                sess_data["last_activity"]
                            )
                        except (ValueError, TypeError):
                            pass

                    # Restore dual tool counts (new format) or derive from old format
                    if sess_data.get("static_tool_count"):
                        session.static_tool_count = sess_data["static_tool_count"]
                    elif sess_data.get("tool_count"):
                        session.static_tool_count = sess_data["tool_count"]
                    elif sess_data.get("active_tools"):
                        session.static_tool_count = len(sess_data["active_tools"])

                    session.dynamic_tool_count = sess_data.get("dynamic_tool_count", 0)
                    session.last_filter_message = sess_data.get("last_filter_message")
                    if sess_data.get("last_filter_time"):
                        try:
                            session.last_filter_time = datetime.fromisoformat(
                                sess_data["last_filter_time"]
                            )
                        except (ValueError, TypeError):
                            pass

                    # Restore activity tracking
                    session.last_tool = sess_data.get("last_tool")
                    if sess_data.get("last_tool_time"):
                        try:
                            session.last_tool_time = datetime.fromisoformat(
                                sess_data["last_tool_time"]
                            )
                        except (ValueError, TypeError):
                            pass
                    session.tool_call_count = sess_data.get("tool_call_count", 0)
                    session.meeting_references = sess_data.get("meeting_references", [])

                    workspace.sessions[session_id] = session
                    restored_sessions += 1

                # Update session names from Cursor's database (sync names if changed)
                cursor_chats, cursor_active_id = list_cursor_chats(workspace_uri)
                cursor_chat_map = {c["composerId"]: c for c in cursor_chats}

                # Update active session from Cursor
                if cursor_active_id and cursor_active_id in workspace.sessions:
                    workspace.active_session_id = cursor_active_id
                for session_id, session in workspace.sessions.items():
                    if session_id in cursor_chat_map:
                        cursor_name = cursor_chat_map[session_id].get("name")
                        if cursor_name and cursor_name != session.name:
                            logger.info(
                                f"Updating session {session_id} name from '{session.name}' to '{cursor_name}'"
                            )
                            session.name = cursor_name

                # Only add workspace if it has sessions or is recent
                if workspace.sessions or not workspace.is_stale(max_age_hours=24):
                    cls._workspaces[workspace_uri] = workspace

            logger.info(
                f"Restored {restored_sessions} session(s) from {len(cls._workspaces)} workspace(s)"
            )
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
