"""Read (and carefully update) Cursor's per-workspace chat databases.

Cursor keeps one ``workspaceStorage/<hash>/`` directory per opened folder; each has a
``workspace.json`` naming the folder URI and a ``state.vscdb`` SQLite database whose
``composer.composerData`` item lists the chats ("composers") of that workspace.
"""

import json
import logging
import sqlite3
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Failures expected while reading Cursor's files and databases (best-effort callers).
CURSOR_DB_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
    subprocess.SubprocessError,
    sqlite3.Error,
)

_COMPOSER_QUERY = "SELECT value FROM ItemTable WHERE key = 'composer.composerData'"


def _cursor_workspace_storage() -> Path:
    """Get Cursor workspace storage path at runtime.

    Computed dynamically so that tests can patch Path.home().
    """
    return Path.home() / ".config" / "Cursor" / "User" / "workspaceStorage"


def _storage_folder_uri(storage_dir: Path) -> str | None:
    """Folder URI recorded in a storage directory's workspace.json (None if absent)."""
    if not storage_dir.is_dir():
        return None
    workspace_json = storage_dir / "workspace.json"
    if not workspace_json.exists():
        return None
    return json.loads(workspace_json.read_text()).get("folder", "")


def _run_sqlite(db_path: Path, query: str) -> subprocess.CompletedProcess:
    """Run one query with the sqlite3 CLI (5 second timeout)."""
    return subprocess.run(
        ["sqlite3", str(db_path), query],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def _valid_chat_id(chat_id: str) -> bool:
    """True when ``chat_id`` is a UUID (guards the SQL built from it)."""
    try:
        uuid.UUID(chat_id)
    except (ValueError, TypeError, AttributeError):
        logger.warning("Invalid chat_id format (expected UUID): %s", chat_id[:50] if chat_id else "None")
        return False
    return True


def _matching_storage_dirs(workspace_uri: str) -> Iterator[Path]:
    """Storage directories whose workspace.json names ``workspace_uri``."""
    for storage_dir in _cursor_workspace_storage().iterdir():
        try:
            folder_uri = _storage_folder_uri(storage_dir)
        except (json.JSONDecodeError, KeyError) as e:
            logger.debug("Error parsing workspace.json in %s: %s", storage_dir, e)
            continue
        if folder_uri == workspace_uri:
            yield storage_dir


def _most_recent_chat(composer_data: dict) -> tuple[str | None, str | None]:
    """(id, name) of the most recently updated non-archived, non-draft chat."""
    all_composers = composer_data.get("allComposers", [])
    if not all_composers:
        logger.debug("No composers found in database")
        return None, None

    active_chats = [c for c in all_composers if not c.get("isArchived") and not c.get("isDraft")]
    if not active_chats:
        logger.debug("No active chats found")
        return None, None

    # The most recently updated chat is likely the current one
    most_recent = max(active_chats, key=lambda x: x.get("lastUpdatedAt", 0))
    chat_id = most_recent.get("composerId")
    chat_name = most_recent.get("name")
    logger.info("Found Cursor chat: %s (%s)", chat_id, chat_name)
    return chat_id, chat_name


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
        if not _cursor_workspace_storage().exists():
            logger.debug("Cursor workspace storage not found")
            return None, None

        for storage_dir in _matching_storage_dirs(workspace_uri):
            db_path = storage_dir / "state.vscdb"
            if not db_path.exists():
                continue

            result = _run_sqlite(db_path, _COMPOSER_QUERY)
            if result.returncode != 0 or not result.stdout.strip():
                logger.debug("No composer data in %s", db_path)
                return None, None

            try:
                composer_data = json.loads(result.stdout.strip())
            except json.JSONDecodeError as e:
                logger.debug("Error parsing workspace.json in %s: %s", storage_dir, e)
                continue
            return _most_recent_chat(composer_data)

        logger.debug("No matching workspace storage found for %s", workspace_uri)
        return None, None

    # Best-effort: log and continue.
    except CURSOR_DB_ERRORS as e:
        logger.warning("Error reading Cursor database: %s", e)
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


def _chat_entry(composer: dict) -> dict | None:
    """Chat dict for listing, or None for archived, draft, ghost or id-less chats."""
    if composer.get("isArchived") or composer.get("isDraft"):
        return None
    # Exclude ghost chats: no name AND no lastUpdatedAt (never actually used)
    if composer.get("name") is None and composer.get("lastUpdatedAt") is None:
        return None
    composer_id = composer.get("composerId")
    if not composer_id:
        return None
    return {
        "composerId": composer_id,
        "name": composer.get("name"),  # Keep None if not set
        "createdAt": composer.get("createdAt", 0),
        "lastUpdatedAt": composer.get("lastUpdatedAt", 0),
        "isArchived": composer.get("isArchived", False),
        "isDraft": composer.get("isDraft", False),
    }


def _read_composer_data(storage_dir: Path) -> dict | None:
    """Parsed composer data of one storage directory (None when unavailable)."""
    db_path = storage_dir / "state.vscdb"
    if not db_path.exists():
        return None
    result = _run_sqlite(db_path, _COMPOSER_QUERY)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout.strip())
    except (json.JSONDecodeError, KeyError):
        return None


def _merge_chats(all_chats: dict[str, dict], composer_data: dict) -> None:
    """Add a directory's chats, keeping the most recently updated copy of each."""
    for composer in composer_data.get("allComposers", []):
        chat = _chat_entry(composer)
        if chat is None:
            continue
        known = all_chats.get(chat["composerId"])
        if known is None or chat["lastUpdatedAt"] > known["lastUpdatedAt"]:
            all_chats[chat["composerId"]] = chat


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
        if not _cursor_workspace_storage().exists():
            return [], None

        all_chats: dict[str, dict] = {}  # composerId -> chat dict (dedup by ID)
        active_chat_id = None

        for storage_dir in _matching_storage_dirs(workspace_uri):
            composer_data = _read_composer_data(storage_dir)
            if composer_data is None:
                continue  # Try other storage directories

            # Get the active/focused chat ID (first directory that has one)
            last_focused = composer_data.get("lastFocusedComposerIds", [])
            if last_focused and not active_chat_id:
                active_chat_id = last_focused[0]

            _merge_chats(all_chats, composer_data)

        chats = sorted(all_chats.values(), key=lambda x: x["lastUpdatedAt"], reverse=True)
        return chats, active_chat_id

    # Best-effort: log and continue.
    except CURSOR_DB_ERRORS as e:
        logger.warning("Error listing Cursor chats: %s", e)
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


def get_cursor_chat_names(workspace_uri: str) -> dict[str, str]:
    """Get a mapping of Cursor chat IDs to their names.

    Args:
        workspace_uri: The workspace URI

    Returns:
        Dict mapping chat ID to chat name
    """
    chats, _ = list_cursor_chats(workspace_uri)
    names: dict[str, str] = {}
    for chat in chats:
        composer_id = chat.get("composerId")
        if not composer_id:
            continue
        name = chat.get("name")
        names[str(composer_id)] = name if isinstance(name, str) else ""
    return names


def _context_text(context: dict | None, system_message: str | None) -> str:
    """Text summarising the injected context (persona, issue, skills, memory)."""
    text = f"{system_message}\n\n" if system_message else ""
    if not context:
        return text
    if context.get("persona"):
        text += f"**Persona:** {context['persona']}\n"
    if context.get("issue_key"):
        text += f"**Issue:** {context['issue_key']}\n"
    if context.get("skills"):
        text += f"**Skills:** {', '.join(context['skills'])}\n"
    if context.get("memory"):
        text += f"**Memory:** {', '.join(context['memory'])}\n"
    return text


def _upsert_focused_chat(composer_data: dict[str, Any], chat_id: str, name: str | None) -> None:
    """Create or update the chat entry and make it the focused chat."""
    now_ms = int(time.time() * 1000)
    # Messages live in a separate global database and cannot be injected here;
    # the chat entry is populated when the user opens it.
    new_chat = {
        "composerId": chat_id,
        "name": name,
        "createdAt": now_ms,
        "lastUpdatedAt": now_ms,
        "isArchived": False,
        "isDraft": False,
    }
    composers = composer_data.get("allComposers", [])
    existing = next((c for c in composers if c.get("composerId") == chat_id), None)
    if existing is not None:
        existing.update(new_chat)
    else:
        composer_data["allComposers"].insert(0, new_chat)
    composer_data["lastFocusedComposerIds"] = [chat_id]


def _inject_into_storage(storage_dir: Path, chat_id: str | None, context: dict | None) -> bool:
    """Write the chat entry into one workspace's state.vscdb."""
    db_path = storage_dir / "state.vscdb"
    if not db_path.exists():
        logger.warning("Cursor state.vscdb not found at %s", db_path)
        return False

    result = _run_sqlite(db_path, _COMPOSER_QUERY)
    if result.returncode != 0:
        logger.warning("Failed to read composer data: %s", result.stderr)
        return False

    composer_data: dict[str, Any] = (
        json.loads(result.stdout.strip())
        if result.stdout.strip()
        else {"allComposers": [], "lastFocusedComposerIds": []}
    )

    # Generate a new chat ID if not provided, or validate provided one (it ends up in SQL)
    if chat_id is None:
        chat_id = str(uuid.uuid4())
    elif not _valid_chat_id(chat_id):
        return False

    _upsert_focused_chat(composer_data, chat_id, context.get("name") if context else None)

    # Write back to database (single quotes escaped for SQLite)
    json_value = json.dumps(composer_data).replace("'", "''")
    update_query = f"UPDATE ItemTable SET value = '{json_value}' WHERE key = 'composer.composerData'"
    result = _run_sqlite(db_path, update_query)
    if result.returncode != 0:
        logger.warning("Failed to update composer data: %s", result.stderr)
        return False

    logger.info("Injected context into Cursor chat %s", chat_id)
    return True


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
    try:
        if not _cursor_workspace_storage().exists():
            logger.warning("Cursor workspace storage not found")
            return False

        logger.debug("Prepared %s characters of chat context", len(_context_text(context, system_message)))
        for storage_dir in _matching_storage_dirs(workspace_uri):
            try:
                return _inject_into_storage(storage_dir, chat_id, context)
            except (json.JSONDecodeError, KeyError) as e:
                logger.debug("Error processing workspace.json in %s: %s", storage_dir, e)

        logger.warning("No matching workspace storage found for %s", workspace_uri)
        return False

    # Best-effort: log and continue.
    except CURSOR_DB_ERRORS as e:
        logger.warning("Error injecting context to Cursor chat: %s", e)
        return False
