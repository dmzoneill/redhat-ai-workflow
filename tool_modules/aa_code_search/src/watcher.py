"""
File watcher for automatic code index updates.

Uses watchfiles (based on Rust notify) for efficient OS-level file watching.
Implements debouncing to avoid excessive re-indexing during rapid saves.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Global watcher instances
_watchers: dict[str, "CodeIndexWatcher"] = {}


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
        self._pending_update: asyncio.Task | None = None
        self._running = False
        self._last_update: datetime | None = None
        self._changes_pending = 0

    @property
    def is_running(self) -> bool:
        """Check if watcher is currently running."""
        return self._running and self._task is not None

    @property
    def last_update(self) -> datetime | None:
        """Get timestamp of last index update."""
        return self._last_update

    @property
    def status(self) -> dict:
        """Get watcher status."""
        return {
            "project": self.project,
            "running": self.is_running,
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "changes_pending": self._changes_pending,
            "debounce_seconds": self.debounce_seconds,
        }

    async def start(self) -> None:
        """Start watching for file changes."""
        if self._running:
            logger.warning(f"Watcher for {self.project} already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._watch_loop())
        logger.info(f"Started watching {self.project} at {self.project_path}")

    async def stop(self) -> None:
        """Stop watching for file changes."""
        self._running = False

        if self._pending_update:
            self._pending_update.cancel()
            self._pending_update = None

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info(f"Stopped watching {self.project}")

    async def _watch_loop(self) -> None:
        """Main watch loop using watchfiles."""
        try:
            import watchfiles
        except ImportError:
            logger.error("watchfiles not installed. Run: pip install watchfiles")
            self._running = False
            return

        # File extensions to watch
        code_extensions = {
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".go",
            ".rs",
            ".java",
            ".rb",
            ".yaml",
            ".yml",
            ".md",
            ".sh",
        }

        # Directories to ignore
        ignore_dirs = {
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

        def should_watch(change_type, path: str) -> bool:
            """Filter function for watchfiles."""
            p = Path(path)

            # Check extension
            if p.suffix.lower() not in code_extensions:
                return False

            # Check for ignored directories
            for part in p.parts:
                if part in ignore_dirs or part.startswith("."):
                    return False

            return True

        try:
            async for changes in watchfiles.awatch(
                self.project_path,
                watch_filter=should_watch,
                stop_event=asyncio.Event() if not self._running else None,
            ):
                if not self._running:
                    break

                # Count pending changes
                self._changes_pending += len(changes)

                # Log changes
                for change_type, path in changes:
                    rel_path = Path(path).relative_to(self.project_path)
                    logger.debug(f"Change detected: {change_type.name} {rel_path}")

                # Cancel previous pending update
                if self._pending_update and not self._pending_update.done():
                    self._pending_update.cancel()

                # Schedule new update after debounce period
                self._pending_update = asyncio.create_task(self._delayed_index())

        except asyncio.CancelledError:
            logger.debug(f"Watch loop cancelled for {self.project}")
        except Exception as e:
            logger.error(f"Watch loop error for {self.project}: {e}")
            self._running = False

    async def _delayed_index(self) -> None:
        """Wait for debounce period then trigger re-index."""
        try:
            await asyncio.sleep(self.debounce_seconds)

            if not self._running:
                return

            logger.info(f"Re-indexing {self.project} ({self._changes_pending} changes)")

            # Run indexing (incremental)
            start = datetime.now()
            stats = self.index_func(self.project, force=False)
            duration = (datetime.now() - start).total_seconds()

            self._last_update = datetime.now()
            self._changes_pending = 0

            logger.info(
                f"Re-indexed {self.project}: "
                f"{stats.get('files_indexed', 0)} files, "
                f"{stats.get('chunks_created', 0)} chunks "
                f"in {duration:.1f}s"
            )

            # Call optional callback
            if self.on_update:
                try:
                    self.on_update(self.project, stats)
                except Exception as e:
                    logger.error(f"on_update callback error: {e}")

        except asyncio.CancelledError:
            logger.debug(f"Delayed index cancelled for {self.project}")
        except Exception as e:
            logger.error(f"Re-indexing error for {self.project}: {e}")


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


