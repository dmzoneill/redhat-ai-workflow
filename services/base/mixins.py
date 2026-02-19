#!/usr/bin/env python3
"""
Reusable Mixins for AI Workflow Daemons.

These mixins extract common patterns that were duplicated across daemons:

- FileWatcherMixin: Directory watching with cache invalidation (config, memory)
- PeriodicWriterMixin: Periodic state persistence (cron, meet)
- dbus_handler: Decorator for standardized D-Bus handler error wrapping

Usage:
    from services.base.mixins import FileWatcherMixin, PeriodicWriterMixin, dbus_handler
"""

import asyncio
import functools
import logging
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


# =============================================================================
# D-BUS HANDLER DECORATOR
# =============================================================================


def dbus_handler(
    result_key: str | None = None,
    error_message: str = "Operation failed",
):
    """Decorator for D-Bus handlers that standardises success/error wrapping.

    Eliminates the repeated try/except pattern found in 50+ D-Bus handlers:

        @dbus_handler(result_key="skills")
        async def _handle_get_skills_list(self, **kwargs):
            return self._load_skills_list()  # Just return the data

    This replaces the verbose pattern:

        async def _handle_get_skills_list(self, **kwargs):
            try:
                skills = self._load_skills_list()
                return {"success": True, "skills": skills}
            except Exception as e:
                logger.error(f"Failed to get skills list: {e}")
                return {"success": False, "error": str(e), "skills": []}

    Args:
        result_key: Key to wrap the return value in. If None, the return value
                    is merged into the response dict (must return a dict).
        error_message: Human-readable prefix for error messages.
    """

    def decorator(
        func: Callable[..., Coroutine[Any, Any, Any]],
    ) -> Callable[..., Coroutine[Any, Any, dict]]:
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs) -> dict:
            try:
                result = await func(self, *args, **kwargs)
                if result_key:
                    return {"success": True, result_key: result}
                elif isinstance(result, dict):
                    return {"success": True, **result}
                else:
                    return {"success": True, "result": result}
            except Exception as e:
                logger.error(f"{error_message}: {e}")
                response: dict[str, Any] = {"success": False, "error": str(e)}
                if result_key:
                    # Include empty default for the expected key
                    response[result_key] = [] if result_key.endswith("s") else None
                return response

        return wrapper

    return decorator


# =============================================================================
# FILE WATCHER FILTER
# =============================================================================


class _StrictPythonFilter:
    """Strict file watcher filter layered on top of watchfiles.DefaultFilter.

    DefaultFilter checks directory *names* but can miss ``__pycache__`` paths
    in edge cases (e.g. when the change event reports a parent directory
    modification rather than the ``.pyc`` file itself).  This filter performs
    full-path component checks as a belt-and-suspenders safeguard.
    """

    _EXCLUDE_DIRS = frozenset(
        {
            "__pycache__",
            ".git",
            ".hg",
            ".svn",
            "node_modules",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
        }
    )
    _EXCLUDE_EXTENSIONS = frozenset(
        {
            ".pyc",
            ".pyo",
            ".pyd",
            ".swp",
            ".swo",
            ".swn",
            ".tmp",
        }
    )

    def __init__(self):
        try:
            from watchfiles import DefaultFilter

            self._inner = DefaultFilter()
        except ImportError:
            self._inner = None

    def __call__(self, change, path: str) -> bool:
        """Return True to include the change, False to exclude."""
        p = Path(path)

        # Exclude if any path component is a known noise directory
        if self._EXCLUDE_DIRS.intersection(p.parts):
            return False

        # Exclude by file extension
        if p.suffix in self._EXCLUDE_EXTENSIONS:
            return False

        # Exclude editor backup files ending with ~
        if p.name.endswith("~"):
            return False

        # Delegate to DefaultFilter for its additional checks
        if self._inner is not None:
            return self._inner(change, path)

        return True


# =============================================================================
# FILE WATCHER MIXIN
# =============================================================================


class FileWatcherMixin:
    """Mixin for daemons that need to watch directories for changes.

    Extracted from config/daemon.py and memory/daemon.py which had nearly
    identical file watching implementations.

    Features:
    - Debouncing: groups rapid file changes into a single callback invocation.
      Default 5s quiet period prevents thrashing from IDE indexing, git ops, etc.
    - Filtering: excludes __pycache__/, .pyc, .swp, and other spurious files
      by default (uses watchfiles.DefaultFilter).

    Usage:
        class MyDaemon(FileWatcherMixin, DaemonDBusBase, BaseDaemon):
            async def startup(self):
                await super().startup()
                self.add_watch(SKILLS_DIR, self._on_skills_changed)
                self.add_watch(MEMORY_DIR, self._on_memory_changed, debounce_seconds=2.0)
                await self.start_watchers()

            async def shutdown(self):
                await self.stop_watchers()
                await super().shutdown()
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._file_watchers: list[asyncio.Task] = []
        self._watch_configs: list[tuple[Path, Callable, float, Any]] = []

    def add_watch(
        self,
        directory: Path,
        callback: Callable,
        debounce_seconds: float = 5.0,
        watch_filter: Any = None,
    ) -> None:
        """Register a directory to watch. Call before start_watchers().

        Args:
            directory: Directory path to watch for changes.
            callback: Async callable invoked with (changes) when files change.
                      Can also be a sync callable.
            debounce_seconds: Minimum quiet period (no new changes) before firing
                              the callback. Groups rapid changes (IDE indexing,
                              git operations, __pycache__ writes) into a single
                              invalidation. Default 5 seconds.
            watch_filter: Optional watchfiles filter instance. If None, uses
                          watchfiles.DefaultFilter which excludes __pycache__/,
                          .pyc, .git/, editor swap files, etc.
        """
        self._watch_configs.append(
            (directory, callback, debounce_seconds, watch_filter)
        )

    async def start_watchers(self) -> None:
        """Start file watchers for all registered directories."""
        for directory, callback, debounce_seconds, watch_filter in self._watch_configs:
            if directory.exists():
                task = asyncio.create_task(
                    self._watch_directory(
                        directory, callback, debounce_seconds, watch_filter
                    ),
                    name=f"file_watcher_{directory.name}",
                )
                self._file_watchers.append(task)

    async def stop_watchers(self) -> None:
        """Cancel all file watcher tasks."""
        for watcher in self._file_watchers:
            watcher.cancel()
        # Await cancellation
        for watcher in self._file_watchers:
            try:
                await watcher
            except asyncio.CancelledError:
                pass
        self._file_watchers.clear()

    @staticmethod
    async def _watch_directory(
        directory: Path,
        callback: Callable,
        debounce_seconds: float = 5.0,
        watch_filter: Any = None,
        max_pending: int = 100,
        max_debounce_seconds: float = 30.0,
    ) -> None:
        """Watch a directory for changes with debouncing, size caps, and filtering.

        Debouncing prevents cache thrashing from rapid file changes (IDE indexing,
        git operations, __pycache__ writes). Changes are accumulated and the
        callback only fires after ``debounce_seconds`` of quiet.

        Safety caps prevent unbounded memory growth when file changes never stop
        (e.g. continuous ``__pycache__``/``.pyc`` writes leaking through filters):

        - ``max_pending``: flush immediately when accumulated changes exceed this
          count, regardless of whether the quiet period has been reached.
        - ``max_debounce_seconds``: flush after this many seconds since the *first*
          unprocessed change, even if new changes keep arriving (prevents debounce
          starvation).

        Filtering uses ``_StrictPythonFilter`` by default, which layers full-path
        ``__pycache__``/``.pyc`` exclusion on top of ``watchfiles.DefaultFilter``.
        """
        debounce_task: asyncio.Task | None = None
        pending_changes: set = set()
        first_pending_time: float | None = None

        try:
            from watchfiles import awatch

            # Use _StrictPythonFilter which does full-path component checks
            # on top of DefaultFilter -- guards against __pycache__/.pyc leaks
            if watch_filter is None:
                watch_filter = _StrictPythonFilter()

            logger.info(
                f"Starting file watcher for {directory} "
                f"(debounce={debounce_seconds}s, max_pending={max_pending}, "
                f"max_debounce={max_debounce_seconds}s, "
                f"filter={type(watch_filter).__name__})"
            )

            async def _flush_pending():
                """Fire callback with accumulated changes and reset state."""
                nonlocal pending_changes, first_pending_time
                # Swap out atomically (no await between these lines)
                changes_to_fire = pending_changes
                pending_changes = set()
                first_pending_time = None
                if changes_to_fire:
                    logger.info(
                        f"Flushing {len(changes_to_fire)} changes in {directory}"
                    )
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(changes_to_fire)
                        else:
                            callback(changes_to_fire)
                    except Exception as e:
                        logger.error(
                            f"File watcher callback error for {directory}: {e}"
                        )

            async def _fire_debounced():
                """Wait for quiet period, then flush."""
                await asyncio.sleep(debounce_seconds)
                await _flush_pending()

            async for changes in awatch(directory, watch_filter=watch_filter):
                pending_changes.update(changes)
                now = time.monotonic()
                if first_pending_time is None:
                    first_pending_time = now

                logger.debug(
                    f"Detected {len(changes)} file changes in {directory}, "
                    f"debouncing ({len(pending_changes)} pending)"
                )

                # --- Safety cap: flush immediately if too many pending ---
                if len(pending_changes) >= max_pending:
                    logger.warning(
                        f"Pending changes cap ({max_pending}) reached for "
                        f"{directory}, flushing immediately"
                    )
                    if debounce_task and not debounce_task.done():
                        debounce_task.cancel()
                        debounce_task = None
                    await _flush_pending()
                    continue

                # --- Safety cap: flush if debounce has been starved too long ---
                if (now - first_pending_time) >= max_debounce_seconds:
                    logger.warning(
                        f"Max debounce timeout ({max_debounce_seconds}s) reached "
                        f"for {directory}, flushing {len(pending_changes)} changes"
                    )
                    if debounce_task and not debounce_task.done():
                        debounce_task.cancel()
                        debounce_task = None
                    await _flush_pending()
                    continue

                # --- Normal debounce: cancel previous timer, start new one ---
                if debounce_task and not debounce_task.done():
                    debounce_task.cancel()

                debounce_task = asyncio.create_task(_fire_debounced())

        except ImportError:
            logger.warning("watchfiles not installed - file watching disabled")
        except asyncio.CancelledError:
            # Clean up any pending debounce task on shutdown
            if debounce_task and not debounce_task.done():
                debounce_task.cancel()
            raise
        except Exception as e:
            logger.error(f"File watcher error for {directory}: {e}")


# =============================================================================
# PERIODIC WRITER MIXIN
# =============================================================================


class PeriodicWriterMixin:
    """Mixin for daemons that periodically persist state to disk.

    Extracted from cron/daemon.py and meet/daemon.py which had identical
    _state_writer_loop implementations.

    Usage:
        class MyDaemon(PeriodicWriterMixin, DaemonDBusBase, BaseDaemon):
            state_write_interval = 60  # seconds

            def write_state(self):
                # Called periodically - write your state to disk
                self._save_my_state()

            async def startup(self):
                await super().startup()
                await self.start_state_writer()

            async def shutdown(self):
                await self.stop_state_writer()
                await super().shutdown()
    """

    state_write_interval: float = 60.0  # Override in subclass

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._state_writer_task: asyncio.Task | None = None

    def write_state(self) -> None:
        """Write current state to disk. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement write_state()")

    async def start_state_writer(self) -> None:
        """Start the periodic state writer."""
        self._state_writer_task = asyncio.create_task(
            self._state_writer_loop(),
            name="state_writer",
        )

    async def stop_state_writer(self) -> None:
        """Stop the periodic state writer and do a final write."""
        if self._state_writer_task and not self._state_writer_task.done():
            self._state_writer_task.cancel()
            try:
                await self._state_writer_task
            except asyncio.CancelledError:
                pass
            self._state_writer_task = None

        # Final state write
        try:
            self.write_state()
        except Exception as e:
            logger.error(f"Final state write failed: {e}")

    async def _state_writer_loop(self) -> None:
        """Periodically write state to disk."""
        shutdown_event = getattr(self, "_shutdown_event", None)

        while True:
            try:
                if shutdown_event:
                    try:
                        await asyncio.wait_for(
                            shutdown_event.wait(), timeout=self.state_write_interval
                        )
                        break  # Shutdown requested
                    except asyncio.TimeoutError:
                        pass
                else:
                    await asyncio.sleep(self.state_write_interval)

                self.write_state()
                logger.debug("Periodic state write complete")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"State writer error: {e}")
                await asyncio.sleep(self.state_write_interval)


# =============================================================================
# STANDARD HEALTH CHECK MIXIN
# =============================================================================


class HealthCheckMixin:
    """Mixin that standardises the health_check() response format.

    Every daemon had an identical health_check() wrapper pattern:

        async def health_check(self):
            self._last_health_check = time.time()
            checks = {"running": self.is_running, ...}
            healthy = all(checks.values())
            return {"healthy": healthy, "checks": checks, "message": ..., "timestamp": ...}

    Now daemons just override get_health_checks() to return their checks:

        def get_health_checks(self) -> dict[str, bool]:
            return {
                "skills_loaded": self._skills_cache is not None,
                "config_loaded": self._config_cache is not None,
            }
    """

    def get_health_checks(self) -> dict[str, bool]:
        """Return service-specific health checks.

        Override in subclasses. The "running" check is added automatically.

        Returns:
            Dict mapping check name to pass/fail bool.
        """
        return {}

    async def health_check(self) -> dict:
        """Perform standardised health check.

        Calls get_health_checks() and wraps in the standard envelope.
        """
        timestamp = time.time()
        self._last_health_check = timestamp  # type: ignore[attr-defined]

        # Combine base running check with service-specific checks
        checks = {"running": getattr(self, "is_running", False)}
        checks.update(self.get_health_checks())

        healthy = all(checks.values())
        name = getattr(self, "name", "service")

        return {
            "healthy": healthy,
            "checks": checks,
            "message": (
                f"{name.title()} daemon is healthy"
                if healthy
                else f"{name.title()} daemon has issues"
            ),
            "timestamp": timestamp,
        }
