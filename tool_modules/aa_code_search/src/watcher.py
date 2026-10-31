"""
File watcher for automatic code index updates.

Uses watchfiles (based on Rust notify) for efficient OS-level file watching.
Implements debouncing to avoid excessive re-indexing during rapid saves.
"""

import asyncio
import importlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Global watcher instances
_watchers: dict[str, "CodeIndexWatcher"] = {}

# File extensions to watch
CODE_EXTENSIONS = frozenset(
    {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".rb", ".yaml", ".yml", ".md", ".sh"}
)

# Directories to ignore
IGNORE_DIRS = frozenset(
    {
        "__pycache__",
        "node_modules",
        "venv",
        ".venv",
        "env",
        "dist",
        "build",
        ".git",
        ".tox",
        "htmlcov",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
        "migrations",
        ".eggs",
    }
)

# Errors from watchfiles or the filesystem that end the watch loop.
WATCH_ERRORS = (OSError, RuntimeError, ValueError)

# Errors from an index run or the on_update callback that are logged and survived.
INDEX_ERRORS = (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError)


def _should_watch(_change_type, path: str) -> bool:
    """watchfiles filter: code files outside ignored and hidden directories."""
    p = Path(path)
    if p.suffix.lower() not in CODE_EXTENSIONS:
        return False
    return not any(part in IGNORE_DIRS or part.startswith(".") for part in p.parts)


@dataclass
class _WatchState:
    """Mutable runtime state of a watcher."""

    running: bool = False
    pending_update: asyncio.Task | None = None
    last_update: datetime | None = None
    changes_pending: int = 0


class CodeIndexWatcher:
    """
    Watches a project directory and triggers re-indexing on changes.

    Features:
    - Debouncing: Waits for quiet period before re-indexing
    - Incremental: Only re-indexes changed files
    - Background: Runs in asyncio task, doesn't block
    - Filtered: Ignores non-code files and common directories
    """

    def __init__(
        self,
        project: str,
        project_path: Path,
        index_func: Callable,
        debounce_seconds: float = 5.0,
        on_update: Callable | None = None,
    ):
        """
        Initialize the watcher.

        Args:
            project: Project name
            project_path: Path to project directory
            index_func: Function to call for indexing (e.g., _index_project)
            debounce_seconds: Wait this long after last change before indexing
            on_update: Optional callback after indexing completes
        """
        self.project = project
        self.project_path = project_path
        self.index_func = index_func
        self.debounce_seconds = debounce_seconds
        self.on_update = on_update

        self._task: asyncio.Task | None = None
        self._state = _WatchState()

    @property
    def is_running(self) -> bool:
        """Check if watcher is currently running."""
        return self._state.running and self._task is not None

    @property
    def last_update(self) -> datetime | None:
        """Get timestamp of last index update."""
        return self._state.last_update

    @property
    def status(self) -> dict:
        """Get watcher status."""
        last_update = self._state.last_update
        return {
            "project": self.project,
            "running": self.is_running,
            "last_update": last_update.isoformat() if last_update else None,
            "changes_pending": self._state.changes_pending,
            "debounce_seconds": self.debounce_seconds,
        }

    async def start(self) -> None:
        """Start watching for file changes."""
        if self._state.running:
            logger.warning("Watcher for %s already running", self.project)
            return

        self._state.running = True
        self._task = asyncio.create_task(self._watch_loop())
        logger.info("Started watching %s at %s", self.project, self.project_path)

    async def stop(self) -> None:
        """Stop watching for file changes."""
        self._state.running = False

        if self._state.pending_update:
            self._state.pending_update.cancel()
            self._state.pending_update = None

        if self._task:
            self._task.cancel()
            # Wait for the loop to finish without swallowing a cancellation
            # of stop() itself; asyncio.wait never raises the task's result.
            await asyncio.wait({self._task})
            self._task = None

        logger.info("Stopped watching %s", self.project)

    async def _watch_loop(self) -> None:
        """Main watch loop using watchfiles."""
        try:
            watchfiles = importlib.import_module("watchfiles")
        except ImportError:
            logger.error("watchfiles not installed. Run: uv add watchfiles")
            self._state.running = False
            return

        try:
            async for changes in watchfiles.awatch(
                self.project_path,
                watch_filter=_should_watch,
                stop_event=asyncio.Event() if not self._state.running else None,
            ):
                if not self._state.running:
                    break
                self._record_changes(changes)

        except asyncio.CancelledError:
            logger.debug("Watch loop cancelled for %s", self.project)
            raise
        except WATCH_ERRORS as e:
            logger.error("Watch loop error for %s: %s", self.project, e)
            self._state.running = False

    def _record_changes(self, changes) -> None:
        """Count and log a batch of changes and (re)schedule the debounced index."""
        self._state.changes_pending += len(changes)

        for change_type, path in changes:
            rel_path = Path(path).relative_to(self.project_path)
            logger.debug("Change detected: %s %s", change_type.name, rel_path)

        # Cancel previous pending update, then schedule a new one after the debounce period
        pending = self._state.pending_update
        if pending and not pending.done():
            pending.cancel()
        self._state.pending_update = asyncio.create_task(self._delayed_index())

    async def _delayed_index(self) -> None:
        """Wait for debounce period then trigger re-index."""
        try:
            await asyncio.sleep(self.debounce_seconds)
        except asyncio.CancelledError:
            logger.debug("Delayed index cancelled for %s", self.project)
            raise

        if not self._state.running:
            return

        logger.info("Re-indexing %s (%s changes)", self.project, self._state.changes_pending)
        try:
            # Run indexing (incremental)
            start = time.monotonic()
            stats = self.index_func(self.project, force=False)
            duration = time.monotonic() - start
        except INDEX_ERRORS as e:
            logger.error("Re-indexing error for %s: %s", self.project, e)
            return

        self._state.last_update = datetime.now().astimezone()
        self._state.changes_pending = 0

        logger.info(
            "Re-indexed %s: %s files, %s chunks in %.1fs",
            self.project,
            stats.get("files_indexed", 0),
            stats.get("chunks_created", 0),
            duration,
        )

        # Call optional callback
        if self.on_update:
            try:
                self.on_update(self.project, stats)
            except INDEX_ERRORS as e:
                logger.error("on_update callback error: %s", e)


def get_watcher(project: str) -> CodeIndexWatcher | None:
    """Get existing watcher for a project."""
    return _watchers.get(project)


def get_all_watchers() -> dict[str, CodeIndexWatcher]:
    """Get all active watchers."""
    return _watchers.copy()


async def start_watcher(
    project: str,
    project_path: Path,
    index_func: Callable,
    debounce_seconds: float = 5.0,
    on_update: Callable | None = None,
) -> CodeIndexWatcher:
    """
    Start a watcher for a project.

    If a watcher already exists for this project, returns the existing one.
    """
    if project in _watchers:
        watcher = _watchers[project]
        if watcher.is_running:
            return watcher

    watcher = CodeIndexWatcher(
        project=project,
        project_path=project_path,
        index_func=index_func,
        debounce_seconds=debounce_seconds,
        on_update=on_update,
    )

    await watcher.start()
    _watchers[project] = watcher

    return watcher


async def stop_watcher(project: str) -> bool:
    """Stop a watcher for a project."""
    if project not in _watchers:
        return False

    watcher = _watchers.pop(project)
    await watcher.stop()
    return True


async def stop_all_watchers() -> int:
    """Stop all watchers. Returns count of stopped watchers."""
    count = 0
    for project in list(_watchers.keys()):
        await stop_watcher(project)
        count += 1
    return count
