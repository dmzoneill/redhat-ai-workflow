"""Read-only access to Cursor's per-workspace storage for the session daemon.

Split out of ``services/session/daemon.py``: finding the configured
workspaces, reading their composer data, hashing their databases, detecting
the active session and searching chat content.
"""

import hashlib
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

COMPOSER_QUERY = "SELECT value FROM ItemTable WHERE key = 'composer.composerData'"
SNIPPET_CONTEXT = 50
MAX_SNIPPETS = 3


def folder_path(folder_uri: str) -> str:
    """Filesystem path of a workspace folder URI."""
    return folder_uri.removeprefix("file://")


def workspace_folder(storage_dir: Path) -> str | None:
    """The workspace folder URI recorded in a storage dir, or None if it has none."""
    workspace_json = storage_dir / "workspace.json"
    if not storage_dir.is_dir() or not workspace_json.exists():
        return None
    folder_uri: str = json.loads(workspace_json.read_text()).get("folder", "")
    return folder_uri


def is_configured(folder_uri: str, configured_paths: set[str]) -> bool:
    """Whether the folder URI resolves to one of the configured repositories."""
    return str(Path(folder_path(folder_uri)).resolve()) in configured_paths


def read_composer_data(db_path: Path) -> dict | None:
    """The ``composer.composerData`` JSON from a workspace database, if set."""
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.cursor().execute(COMPOSER_QUERY).fetchone()
    if not row or not row[0]:
        return None
    data: dict = json.loads(row[0])
    return data


def live_composers(composer_data: dict) -> list[dict]:
    """Composers that are neither archived nor drafts."""
    return [c for c in composer_data.get("allComposers", []) if not c.get("isArchived") and not c.get("isDraft")]


def state_hash(storage: Path, configured_paths: set[str]) -> str:
    """Hash of the mtimes and sizes of the configured workspaces' databases."""
    if not storage.exists():
        return ""
    hash_data = []
    for storage_dir in storage.iterdir():
        try:
            folder_uri = workspace_folder(storage_dir)
            if folder_uri is None or not is_configured(folder_uri, configured_paths):
                continue
            db_path = storage_dir / "state.vscdb"
            if db_path.exists():
                st = db_path.stat()
                hash_data.append(f"{db_path}:{st.st_mtime}:{st.st_size}")
        except (OSError, ValueError, AttributeError):
            continue
    # A change detector, not a security hash.
    return hashlib.sha256("|".join(sorted(hash_data)).encode()).hexdigest()


def storage_map(storage: Path, configured_paths: set[str]) -> dict[str, Path]:
    """Map configured workspace URIs to their storage directories."""
    mapping: dict[str, Path] = {}
    if not storage.exists():
        return mapping
    for storage_dir in storage.iterdir():
        try:
            folder_uri = workspace_folder(storage_dir)
        except (json.JSONDecodeError, OSError):
            continue
        if folder_uri is not None and is_configured(folder_uri, configured_paths):
            mapping[folder_uri] = storage_dir
    return mapping


@dataclass
class ActiveSessionScanner:
    """Detect active sessions cheaply, re-reading only databases that changed."""

    storage: Path
    configured_paths: set[str] = field(default_factory=set)
    workspaces: dict[str, Path] = field(default_factory=dict)
    db_mtimes: dict[str, float] = field(default_factory=dict)
    session_counts: dict[str, int] = field(default_factory=dict)

    def refresh_workspaces(self) -> None:
        """Rebuild the configured-workspace to storage-dir map."""
        self.workspaces = storage_map(self.storage, self.configured_paths)
        logger.info("Built workspace storage map: %d configured workspaces", len(self.workspaces))

    def scan(self) -> tuple[dict[str, str | None], int]:
        """Active session ID per workspace, and the total live session count."""
        if not self.workspaces:
            self.refresh_workspaces()

        active: dict[str, str | None] = {}
        total = 0
        for folder_uri, storage_dir in self.workspaces.items():
            db_path = storage_dir / "state.vscdb"
            try:
                if not db_path.exists():
                    continue
                mtime = db_path.stat().st_mtime
                if mtime == self.db_mtimes.get(str(db_path), 0):
                    total += self.session_counts.get(folder_uri, 0)
                    continue
                composer_data = read_composer_data(db_path)
            except (json.JSONDecodeError, sqlite3.Error) as e:
                logger.debug("Error reading workspace %s: %s", storage_dir, e)
                continue
            if composer_data is None:
                continue
            last_focused = composer_data.get("lastFocusedComposerIds", [])
            active[folder_uri] = last_focused[0] if last_focused else None
            count = len(live_composers(composer_data))
            total += count
            self.session_counts[folder_uri] = count
            self.db_mtimes[str(db_path)] = mtime
        return active, total


def snippet(text: str, match: re.Match) -> str:
    """Text around a match, with ellipses where it was cut."""
    start = max(0, match.start() - SNIPPET_CONTEXT)
    end = min(len(text), match.end() + SNIPPET_CONTEXT)
    result = text[start:end]
    if start > 0:
        result = "..." + result
    if end < len(text):
        result += "..."
    return result


def content_matches(conversation: list[dict], query: str) -> list[dict]:
    """Snippets of each message in a conversation that contains *query*."""
    query_lower = query.lower()
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    matches = []
    for msg in conversation:
        text = msg.get("text", "") or msg.get("content", "")
        if not text or query_lower not in text.lower():
            continue
        match = pattern.search(text)
        if match:
            matches.append({"snippet": snippet(text, match), "role": msg.get("role", "unknown")})
    return matches


def search_composer(composer: dict, query: str, folder_uri: str) -> dict | None:
    """Search result for one session, or None if neither its name nor content match."""
    composer_id = composer.get("composerId", "")
    name = composer.get("name", "")
    name_match = query.lower() in (name or "").lower()
    matches = content_matches(composer.get("conversation", []), query)
    if not name_match and not matches:
        return None
    return {
        "session_id": composer_id,
        "name": name or f"Session {composer_id[:8]}",
        "project": folder_path(folder_uri).split("/")[-1],
        "workspace_uri": folder_uri,
        "name_match": name_match,
        "content_matches": matches[:MAX_SNIPPETS],
        "match_count": len(matches),
        "last_updated": composer.get("lastUpdatedAt"),
    }


def search_workspace(storage_dir: Path, query: str, configured_paths: set[str], limit: int) -> list[dict]:
    """Search results from one storage dir, at most *limit*."""
    folder_uri = workspace_folder(storage_dir)
    if folder_uri is None or not is_configured(folder_uri, configured_paths):
        return []
    db_path = storage_dir / "state.vscdb"
    if not db_path.exists():
        return []
    composer_data = read_composer_data(db_path)
    if composer_data is None:
        return []
    results: list[dict] = []
    for composer in live_composers(composer_data):
        result = search_composer(composer, query, folder_uri)
        if result:
            results.append(result)
            if len(results) >= limit:
                break
    return results


def search_chats(storage: Path, query: str, configured_paths: set[str], limit: int) -> list[dict]:
    """Search session names and chat content across the configured workspaces."""
    results: list[dict] = []
    for storage_dir in storage.iterdir():
        try:
            results.extend(search_workspace(storage_dir, query, configured_paths, limit - len(results)))
        except (json.JSONDecodeError, sqlite3.Error) as e:
            logger.debug("Error searching %s: %s", storage_dir, e)
            continue
        if len(results) >= limit:
            break
    results.sort(key=lambda x: (not x["name_match"], -x["match_count"]))
    return results
