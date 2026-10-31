"""Tests for the code index file watcher."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tool_modules.aa_code_search.src import watcher as watcher_mod


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/repo/src/app.py", True),
        ("/repo/README.MD", True),
        ("/repo/image.png", False),
        ("/repo/node_modules/x.js", False),
        ("/repo/.hidden/x.py", False),
        ("/repo/build/x.py", False),
    ],
)
def test_should_watch(path, expected):
    """Only code files outside ignored or hidden directories are watched."""
    assert vars(watcher_mod)["_should_watch"](None, path) is expected


def _watcher(tmp_path, index_func, **kwargs):
    return watcher_mod.CodeIndexWatcher("proj", tmp_path, index_func, debounce_seconds=0, **kwargs)


def test_change_batch_triggers_one_debounced_index(tmp_path, monkeypatch):
    """Two quick batches cancel the first index and run the second once."""
    calls = []
    updates = []
    seen = []

    def index(project, force):
        calls.append((project, force))
        return {"files_indexed": 2, "chunks_created": 5}

    async def fake_awatch(path, watch_filter, stop_event):
        seen.append((path, watch_filter, stop_event))
        change = SimpleNamespace(name="modified")
        yield [(change, str(tmp_path / "a.py"))]
        yield [(change, str(tmp_path / "b.py"))]
        await asyncio.sleep(3600)

    monkeypatch.setitem(sys.modules, "watchfiles", SimpleNamespace(awatch=fake_awatch))

    async def scenario():
        w = _watcher(tmp_path, index, on_update=lambda project, stats: updates.append(stats))
        await w.start()
        assert w.is_running
        for _ in range(20):
            await asyncio.sleep(0.01)
        status = w.status
        await w.stop()
        return w, status

    w, status = asyncio.run(scenario())
    assert seen == [(tmp_path, vars(watcher_mod)["_should_watch"], None)]
    assert calls == [("proj", False)]
    assert updates == [{"files_indexed": 2, "chunks_created": 5}]
    assert status["changes_pending"] == 0
    assert status["last_update"] is not None
    assert not w.is_running


def test_index_errors_are_logged_not_raised(tmp_path):
    """A failing index run leaves the pending count for the next run."""

    def index(project, force):
        raise OSError("disk")

    async def scenario():
        w = _watcher(tmp_path, index)
        vars(w)["_state"].running = True
        vars(w)["_state"].changes_pending = 3
        await vars(watcher_mod.CodeIndexWatcher)["_delayed_index"](w)
        return w

    w = asyncio.run(scenario())
    assert w.status["changes_pending"] == 3
    assert w.last_update is None


def test_delayed_index_reraises_cancellation(tmp_path):
    """Cancelling a pending index propagates CancelledError."""

    async def scenario():
        w = watcher_mod.CodeIndexWatcher("proj", tmp_path, lambda *a, **k: {}, debounce_seconds=60)
        vars(w)["_state"].running = True
        task = asyncio.create_task(vars(watcher_mod.CodeIndexWatcher)["_delayed_index"](w))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return task

    assert asyncio.run(scenario()).cancelled()


def test_missing_watchfiles_stops_watcher(tmp_path, monkeypatch):
    """Without watchfiles the loop exits and the watcher is not running."""

    monkeypatch.setitem(sys.modules, "watchfiles", None)

    async def scenario():
        w = _watcher(tmp_path, lambda *a, **k: {})
        await w.start()
        await asyncio.sleep(0.01)
        running = w.is_running
        await w.stop()
        return running

    assert asyncio.run(scenario()) is False


def test_start_and_stop_all_watchers(tmp_path, monkeypatch):
    """Module helpers track, reuse and stop watchers."""

    async def idle_awatch(*_args, **_kwargs):
        await asyncio.sleep(3600)
        yield set()

    monkeypatch.setitem(sys.modules, "watchfiles", SimpleNamespace(awatch=idle_awatch))

    async def scenario():
        first = await watcher_mod.start_watcher("p1", Path(tmp_path), lambda *a, **k: {})
        again = await watcher_mod.start_watcher("p1", Path(tmp_path), lambda *a, **k: {})
        assert first is again
        assert set(watcher_mod.get_all_watchers()) == {"p1"}
        assert await watcher_mod.stop_all_watchers() == 1
        assert not await watcher_mod.stop_watcher("p1")

    asyncio.run(scenario())
