"""Tests for the session daemon and its helpers (services/session)."""

import asyncio
import importlib
import json
import os
import sqlite3
from pathlib import Path
from typing import ClassVar

import pytest

from services.session import cursor_db, sync_work
from services.session.cursor_db import ActiveSessionScanner, content_matches, folder_path, search_chats, state_hash
from services.session.daemon import SessionDaemon
from services.session.sync_work import SessionTracker, write_state_file

daemon_module = importlib.import_module(SessionDaemon.__module__)


def _workspace(storage: Path, name: str, folder: str, composers: list[dict], focused: list[str]) -> Path:
    path = storage / name
    path.mkdir(parents=True)
    (path / "workspace.json").write_text(json.dumps({"folder": folder}), encoding="utf-8")
    with sqlite3.connect(path / "state.vscdb") as conn:
        conn.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        value = json.dumps({"allComposers": composers, "lastFocusedComposerIds": focused})
        conn.execute("INSERT INTO ItemTable VALUES ('composer.composerData', ?)", (value,))
    return path


@pytest.fixture(name="storage")
def storage_fixture(tmp_path: Path) -> Path:
    """Cursor workspace storage with one configured and one other workspace."""
    storage = tmp_path / "workspaceStorage"
    composers: list[dict] = [
        {"composerId": "c1aaaaaaaa", "name": "Fix login", "conversation": [{"text": "a LOGIN bug", "role": "user"}]},
        {"composerId": "c2", "name": "", "conversation": [{"content": "login here"}]},
        {"composerId": "c3", "name": "login", "isArchived": True},
    ]
    _workspace(storage, "a", "file:///repo/a", composers, ["c1aaaaaaaa"])
    _workspace(storage, "b", "file:///other", [{"composerId": "z", "name": "login"}], [])
    (storage / "loose-file").write_text("x", encoding="utf-8")
    return storage


class FakeRegistry:
    """Stand-in for WorkspaceRegistry that records calls."""

    workspaces: ClassVar[dict] = {}
    calls: ClassVar[list] = []

    @classmethod
    def load_from_disk(cls):
        """Record a load."""
        cls.calls.append("load")

    @classmethod
    def save_to_disk(cls):
        """Record a save."""
        cls.calls.append("save")

    @classmethod
    def count(cls):
        """Number of workspaces."""
        return len(cls.workspaces)

    @classmethod
    def remove(cls, uri):
        """Remove a workspace."""
        return cls.workspaces.pop(uri, None) is not None

    @classmethod
    def get_or_create(cls, uri, ensure_session=False):
        """Register a workspace."""
        del ensure_session
        cls.workspaces.setdefault(uri, {"sessions": {}})

    @classmethod
    def sync_all_with_cursor(cls, skip_content_scan=False):
        """Pretend full sync."""
        return {"skip": skip_content_scan}

    @classmethod
    def sync_sessions_with_cursor(cls, session_ids=None):
        """Pretend partial sync."""
        cls.calls.append(("sync", list(session_ids or [])))
        return {"updated": len(session_ids or [])}

    @classmethod
    def get_all_as_dict(cls):
        """Workspaces as dicts."""
        return dict(cls.workspaces)

    @classmethod
    def get_all_sessions(cls):
        """Fourteen sessions."""
        return [{"session_id": f"s{i}"} for i in range(1, 15)]


@pytest.fixture(name="daemon")
def daemon_fixture(storage, tmp_path, monkeypatch) -> SessionDaemon:
    """SessionDaemon over the fixture storage with a fake registry and temp state file."""
    state_file = tmp_path / "state" / "session_state.json"
    FakeRegistry.workspaces = {"file:///repo/a": {"sessions": {"s1": {}}}, "file:///gone": {"sessions": {}}}
    FakeRegistry.calls = []
    for module in (daemon_module, sync_work):
        monkeypatch.setattr(module, "WorkspaceRegistry", FakeRegistry)
        monkeypatch.setattr(module, "SESSION_STATE_FILE", state_file)
    monkeypatch.setattr(daemon_module, "CURSOR_WORKSPACE_STORAGE", storage)
    monkeypatch.setattr(sync_work.write_state_file, "__defaults__", (state_file,))
    d = SessionDaemon(enable_dbus=False)
    d.__dict__["_scanner"] = ActiveSessionScanner(storage, {"/repo/a"})
    return d


def _private(obj, name: str):
    """Look up a private method by name (the sync passes are internal)."""
    return getattr(obj, name)


def _handlers(d: SessionDaemon) -> dict:
    handlers: dict = d.__dict__["_custom_handlers"]
    return handlers


# ==================== cursor_db ====================


def test_folder_path_strips_file_scheme():
    """file:// URIs become paths; plain paths are unchanged."""
    assert folder_path("file:///repo/a") == "/repo/a"
    assert folder_path("/repo/a") == "/repo/a"


def test_content_matches_snippets():
    """Snippets keep 50 characters of context with ellipses."""
    text = "x" * 60 + "needle" + "y" * 60
    matches = content_matches([{"text": text, "role": "user"}, {"content": "none"}], "NEEDLE")
    assert len(matches) == 1
    match = matches[0]
    assert match["snippet"] == "..." + "x" * 50 + "needle" + "y" * 50 + "..."
    assert match["role"] == "user"


def test_search_chats_configured_only(storage):
    """Archived sessions and unconfigured workspaces are skipped; name matches sort first."""
    results = search_chats(storage, "login", {"/repo/a"}, 20)
    assert [r["session_id"] for r in results] == ["c1aaaaaaaa", "c2"]
    assert results[1]["name"] == "Session c2"
    assert len(search_chats(storage, "login", {"/repo/a"}, 1)) == 1


def test_state_hash_changes_with_db(storage):
    """The hash changes when a configured database changes."""
    before = state_hash(storage, {"/repo/a"})
    assert before == state_hash(storage, {"/repo/a"})
    db = storage / "a" / "state.vscdb"
    os.utime(db, (db.stat().st_atime, db.stat().st_mtime + 10))
    assert state_hash(storage, {"/repo/a"}) != before
    assert state_hash(storage / "missing", set()) == ""


def test_scanner_caches_unchanged_databases(storage, monkeypatch):
    """An unchanged database is not re-read; its cached count is reused."""
    scanner = ActiveSessionScanner(storage, {"/repo/a"})
    assert scanner.scan() == ({"file:///repo/a": "c1aaaaaaaa"}, 2)

    def fail(_):
        raise AssertionError("database re-read")

    monkeypatch.setattr(cursor_db, "read_composer_data", fail)
    assert scanner.scan() == ({}, 2)


# ==================== sync_work ====================


def test_tracker_recent_order_and_batches():
    """Most recent first, capped; batches wrap around."""
    tracker = SessionTracker(max_recent=2, batch_size=2)
    for sid in ("a", "b", "a", "c", None):
        tracker.mark_active(sid)
    assert tracker.recent == ["c", "a"]
    assert tracker.last_active == "c"
    ids = ["1", "2", "3"]
    assert tracker.next_batch(ids) == (0, ["1", "2"])
    assert tracker.next_batch(ids) == (2, ["3"])
    assert tracker.next_batch(ids) == (0, ["1", "2"])


def test_write_state_file_cleans_up_on_error(tmp_path):
    """A failed write leaves no temp file and the old state untouched."""
    target = tmp_path / "state.json"
    write_state_file({"a": 1}, target)
    with pytest.raises(TypeError):
        write_state_file({1j: 1}, target)
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


# ==================== SessionDaemon ====================


async def test_handlers_registered(daemon):
    """D-Bus handler names are unchanged."""
    assert set(_handlers(daemon)) == {
        "search_chats",
        "get_sessions",
        "refresh_now",
        "get_state",
        "write_state",
        "remove_workspace",
    }


async def test_search_and_state_handlers(daemon):
    """Search counts calls; state handlers read the state file once it exists."""
    result = await _handlers(daemon)["search_chats"](query="login")
    assert result["total_found"] == 2
    assert await _handlers(daemon)["get_sessions"]() == {"sessions": [], "session_count": 0}
    assert (await _handlers(daemon)["refresh_now"]())["sync_count"] == 1
    state = await _handlers(daemon)["get_state"]()
    assert state["sync_type"] == "full"
    assert (await daemon.get_service_stats())["search_count"] == 1


async def test_remove_workspace(daemon):
    """Missing URI, unknown workspace and a real removal."""
    remove = _handlers(daemon)["remove_workspace"]
    assert (await remove())["error"] == "uri required"
    assert (await remove(uri="file:///nope"))["success"] is False
    assert (await remove(uri="file:///gone"))["success"] is True
    assert "file:///gone" not in FakeRegistry.workspaces
    assert "save" in FakeRegistry.calls


async def test_fast_sync_detects_changes(daemon):
    """First scan marks the active session; a count change triggers a full sync."""
    assert await _private(daemon, "_do_fast_sync")() is True
    assert (await daemon.get_service_stats())["last_active_session"] == "c1aaaaaaaa"
    assert await _private(daemon, "_do_fast_sync")() is False


async def test_recent_and_background_sync(daemon):
    """Recent sync covers recent sessions; background batches the rest."""
    tracker = daemon.__dict__["_tracker"]
    tracker.mark_active("s1")
    assert await _private(daemon, "_do_recent_sync")() == {"updated": 1}
    assert await _private(daemon, "_do_background_sync")() == {"updated": 10}
    assert FakeRegistry.calls[-1] == ("sync", [f"s{i}" for i in range(2, 12)])


async def test_shutdown_cancels_loops(daemon):
    """Shutdown cancels the sync loops and waits for them."""
    tasks = [asyncio.create_task(asyncio.sleep(60)) for _ in range(3)]
    daemon.__dict__["_tasks"] = tasks
    await daemon.shutdown()
    assert all(t.cancelled() for t in tasks)


async def test_health_check(daemon):
    """Healthy needs running and configured paths."""
    daemon.is_running = True
    result = await daemon.health_check()
    assert result["healthy"] is True
    assert result["checks"]["recent_sync"] is False
