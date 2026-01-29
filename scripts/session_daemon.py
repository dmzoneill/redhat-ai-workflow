#!/usr/bin/env python3
"""
Session Daemon - Cursor Session State Manager

A standalone service that manages Cursor session state with real-time updates.
Designed to run as a systemd user service.

Features:
- Watches Cursor's database for session changes
- D-Bus IPC for external control and queries
- Full-text search of chat content
- Real-time state change notifications
- Periodic sync with workspace_states.json

Usage:
    python scripts/session_daemon.py                # Run daemon
    python scripts/session_daemon.py --status       # Check if running
    python scripts/session_daemon.py --stop         # Stop running daemon
    python scripts/session_daemon.py --search "query"  # Search chats

Systemd:
    systemctl --user start bot-session
    systemctl --user status bot-session
    systemctl --user stop bot-session

D-Bus:
    Service: com.aiworkflow.BotSession
    Path: /com/aiworkflow/BotSession

    Methods:
    - GetSessions() -> JSON list of sessions
    - SearchChats(query: str, limit: int) -> JSON search results
    - RefreshNow() -> Trigger immediate sync
    - GetState() -> Full workspace state JSON

    Signals:
    - StateChanged(change_type: str) - Emitted when sessions change
"""

import argparse
import asyncio
import fcntl
import hashlib
import json
import logging
import os
import re
import signal
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.dbus_base import DaemonDBusBase, get_client  # noqa: E402

LOCK_FILE = Path("/tmp/session-daemon.lock")
PID_FILE = Path("/tmp/session-daemon.pid")

# Import centralized paths
from server.paths import AA_CONFIG_DIR, SESSION_STATE_FILE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger(__name__)


class SingleInstance:
    """Ensures only one instance of the daemon runs at a time."""

    def __init__(self):
        self._lock_file = None
        self._acquired = False

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if successful."""
        try:
            self._lock_file = open(LOCK_FILE, "w")
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            PID_FILE.write_text(str(os.getpid()))
            self._acquired = True
            return True
        except OSError:
            return False

    def release(self):
        """Release the lock."""
        if self._lock_file:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception:
                pass
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except Exception:
                pass
        self._acquired = False

    def get_running_pid(self) -> int | None:
        """Get PID of running instance, or None if not running."""
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                os.kill(pid, 0)
                return pid
            except (ValueError, OSError):
                pass
        return None


class SessionDaemon(DaemonDBusBase):
    """Main session daemon with D-Bus support."""

    # D-Bus configuration
    service_name = "com.aiworkflow.BotSession"
    object_path = "/com/aiworkflow/BotSession"
    interface_name = "com.aiworkflow.BotSession"

    def __init__(self, verbose: bool = False, enable_dbus: bool = True):
        super().__init__()
        self.verbose = verbose
        self.enable_dbus = enable_dbus
        self._shutdown_event = asyncio.Event()

        # State tracking
        self._last_state_hash: str = ""
        self._sync_count: int = 0
        self._last_sync_time: float = 0
        self._search_count: int = 0
        self._configured_paths: set[str] = set()

        # Sync interval (seconds)
        self._sync_interval: float = 10.0
        self._watch_interval: float = 2.0  # Check for changes more frequently

        # Register custom D-Bus method handlers
        self.register_handler("search_chats", self._handle_search_chats)
        self.register_handler("get_sessions", self._handle_get_sessions)
        self.register_handler("refresh_now", self._handle_refresh_now)
        self.register_handler("get_state", self._handle_get_state)
        self.register_handler("write_state", self._handle_write_state)

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return session-specific statistics."""
        return {
            "sync_count": self._sync_count,
            "last_sync_time": self._last_sync_time,
            "search_count": self._search_count,
            "configured_workspaces": len(self._configured_paths),
            "sync_interval": self._sync_interval,
        }

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        base = self.get_base_stats()
        service = await self.get_service_stats()

        # Add current session count
        try:
            if SESSION_STATE_FILE.exists():
                data = json.loads(SESSION_STATE_FILE.read_text())
                service["session_count"] = data.get("session_count", 0)
                service["workspace_count"] = data.get("workspace_count", 0)
        except Exception:
            service["session_count"] = 0
            service["workspace_count"] = 0

        return {**base, **service}

    async def health_check(self) -> dict:
        """Perform a health check on the session daemon."""
        now = time.time()
        self._last_health_check = now

        checks = {
            "running": self.is_running,
            "config_loaded": len(self._configured_paths) > 0,
        }

        # Check if we've synced recently
        if self._last_sync_time > 0:
            time_since_sync = now - self._last_sync_time
            checks["recent_sync"] = time_since_sync < (self._sync_interval * 3)
        else:
            checks["recent_sync"] = False

        # Check uptime
        if self.start_time:
            checks["uptime_ok"] = (now - self.start_time) > 5
        else:
            checks["uptime_ok"] = False

        healthy = all(checks.values())
        message = "Session daemon is healthy" if healthy else f"Unhealthy: {[k for k, v in checks.items() if not v]}"

        return {
            "healthy": healthy,
            "checks": checks,
            "message": message,
            "timestamp": now,
            "sync_count": self._sync_count,
        }

    # ==================== D-Bus Method Handlers ====================

    async def _handle_search_chats(self, query: str, limit: int = 20) -> dict:
        """Search chat content across all configured workspaces."""
        self._search_count += 1
        results = []

        try:
            workspace_storage = Path.home() / ".config" / "Cursor" / "User" / "workspaceStorage"
            if not workspace_storage.exists():
                return {"results": [], "query": query, "error": "Cursor storage not found"}

            query_lower = query.lower()
            query_pattern = re.compile(re.escape(query), re.IGNORECASE)

            for storage_dir in workspace_storage.iterdir():
                if not storage_dir.is_dir():
                    continue

                workspace_json = storage_dir / "workspace.json"
                if not workspace_json.exists():
                    continue

                try:
                    workspace_data = json.loads(workspace_json.read_text())
                    folder_uri = workspace_data.get("folder", "")

                    # Convert to path and check if configured
                    if folder_uri.startswith("file://"):
                        workspace_path = folder_uri[7:]
                    else:
                        workspace_path = folder_uri

                    workspace_path_resolved = str(Path(workspace_path).resolve())
                    if workspace_path_resolved not in self._configured_paths:
                        continue

                    # Query the database
                    db_path = storage_dir / "state.vscdb"
                    if not db_path.exists():
                        continue

                    conn = sqlite3.connect(str(db_path))
                    cursor = conn.cursor()
                    cursor.execute("SELECT value FROM ItemTable WHERE key = 'composer.composerData'")
                    row = cursor.fetchone()
                    conn.close()

                    if not row or not row[0]:
                        continue

                    composer_data = json.loads(row[0])
                    all_composers = composer_data.get("allComposers", [])

                    for composer in all_composers:
                        if composer.get("isArchived") or composer.get("isDraft"):
                            continue

                        composer_id = composer.get("composerId", "")
                        name = composer.get("name", "")
                        conversation = composer.get("conversation", [])

                        # Search in name
                        name_match = query_lower in (name or "").lower()

                        # Search in conversation content
                        content_matches = []
                        for msg in conversation:
                            text = msg.get("text", "") or msg.get("content", "")
                            if text and query_lower in text.lower():
                                # Extract snippet around match
                                match = query_pattern.search(text)
                                if match:
                                    start = max(0, match.start() - 50)
                                    end = min(len(text), match.end() + 50)
                                    snippet = text[start:end]
                                    if start > 0:
                                        snippet = "..." + snippet
                                    if end < len(text):
                                        snippet = snippet + "..."
                                    content_matches.append(
                                        {
                                            "snippet": snippet,
                                            "role": msg.get("role", "unknown"),
                                        }
                                    )

                        if name_match or content_matches:
                            # Get project name from workspace path
                            project = workspace_path.split("/")[-1]

                            results.append(
                                {
                                    "session_id": composer_id,
                                    "name": name or f"Session {composer_id[:8]}",
                                    "project": project,
                                    "workspace_uri": folder_uri,
                                    "name_match": name_match,
                                    "content_matches": content_matches[:3],  # Limit snippets
                                    "match_count": len(content_matches),
                                    "last_updated": composer.get("lastUpdatedAt"),
                                }
                            )

                            if len(results) >= limit:
                                break

                except (json.JSONDecodeError, sqlite3.Error) as e:
                    logger.debug(f"Error searching {storage_dir}: {e}")
                    continue

                if len(results) >= limit:
                    break

            # Sort by relevance (name matches first, then by match count)
            results.sort(key=lambda x: (not x["name_match"], -x["match_count"]))

            return {
                "results": results[:limit],
                "query": query,
                "total_found": len(results),
            }

        except Exception as e:
            logger.error(f"Search error: {e}")
            return {"results": [], "query": query, "error": str(e)}

    async def _handle_get_sessions(self) -> dict:
        """Get all sessions from session state."""
        try:
            if SESSION_STATE_FILE.exists():
                data = json.loads(SESSION_STATE_FILE.read_text())
                return {
                    "sessions": data.get("sessions", []),
                    "session_count": data.get("session_count", 0),
                    "updated_at": data.get("updated_at"),
                }
            return {"sessions": [], "session_count": 0}
        except Exception as e:
            return {"sessions": [], "error": str(e)}

    async def _handle_refresh_now(self) -> dict:
        """Trigger immediate sync."""
        try:
            await self._do_sync()
            return {"success": True, "sync_count": self._sync_count}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_get_state(self) -> dict:
        """Get full session state."""
        try:
            if SESSION_STATE_FILE.exists():
                return json.loads(SESSION_STATE_FILE.read_text())
            return {}
        except Exception as e:
            return {"error": str(e)}

    async def _handle_write_state(self) -> dict:
        """Write state to file immediately (for UI refresh requests)."""
        try:
            await self._do_sync()
            return {"success": True, "file": str(SESSION_STATE_FILE)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== Core Logic ====================

    def _load_configured_paths(self):
        """Load configured repository paths from config.json."""
        try:
            from server.config_manager import config as config_manager

            repos = config_manager.get("repositories", default={})
            self._configured_paths = set()
            for repo in repos.values():
                local_path = repo.get("path", "")
                if local_path:
                    self._configured_paths.add(str(Path(local_path).resolve()))
            logger.info(f"Loaded {len(self._configured_paths)} configured repository paths")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self._configured_paths = set()

    def _compute_state_hash(self) -> str:
        """Compute a hash of the current Cursor session state."""
        try:
            workspace_storage = Path.home() / ".config" / "Cursor" / "User" / "workspaceStorage"
            if not workspace_storage.exists():
                return ""

            # Hash the modification times and sizes of relevant DB files
            hash_data = []
            for storage_dir in workspace_storage.iterdir():
                if not storage_dir.is_dir():
                    continue

                workspace_json = storage_dir / "workspace.json"
                if not workspace_json.exists():
                    continue

                try:
                    workspace_data = json.loads(workspace_json.read_text())
                    folder_uri = workspace_data.get("folder", "")
                    if folder_uri.startswith("file://"):
                        workspace_path = folder_uri[7:]
                    else:
                        workspace_path = folder_uri

                    workspace_path_resolved = str(Path(workspace_path).resolve())
                    if workspace_path_resolved not in self._configured_paths:
                        continue

                    db_path = storage_dir / "state.vscdb"
                    if db_path.exists():
                        stat = db_path.stat()
                        hash_data.append(f"{db_path}:{stat.st_mtime}:{stat.st_size}")
                except Exception:
                    continue

            return hashlib.md5("|".join(sorted(hash_data)).encode()).hexdigest()
        except Exception as e:
            logger.debug(f"Error computing state hash: {e}")
            return ""

    async def _do_sync(self):
        """Sync session data to session_state.json.

        Each service writes to its own state file. The VS Code extension
        reads all state files on refresh and merges them for display.
        This prevents race conditions - no shared file between services.
        """
        try:
            from server.workspace_state import WorkspaceRegistry

            # Load from disk (registry is per-process, so we need to load first)
            WorkspaceRegistry.load_from_disk()

            # Ensure configured workspaces exist
            for workspace_path in self._configured_paths:
                # Convert path to file:// URI if needed
                workspace_uri = workspace_path
                if not workspace_uri.startswith("file://"):
                    workspace_uri = f"file://{workspace_path}"
                WorkspaceRegistry.get_or_create(workspace_uri, ensure_session=False)

            # Sync with Cursor's database
            sync_result = WorkspaceRegistry.sync_all_with_cursor()

            # Get all workspace states
            all_states = WorkspaceRegistry.get_all_as_dict()
            all_sessions = WorkspaceRegistry.get_all_sessions()

            # Build session state
            session_state = {
                "workspaces": all_states,
                "sessions": all_sessions,
                "workspace_count": len(all_states),
                "session_count": (
                    len(all_sessions)
                    if all_sessions
                    else sum(len(ws.get("sessions", {})) for ws in all_states.values())
                ),
                "last_sync": sync_result,
                "updated_at": datetime.now().isoformat(),
            }

            # Write to our own state file atomically
            self._write_state_file(session_state)

            self._sync_count += 1
            self._last_sync_time = time.time()
            logger.debug(f"Session sync: {len(all_sessions)} sessions, {sync_result}")
            self.record_successful_operation()

        except Exception as e:
            logger.error(f"Session sync error: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            self.record_failed_operation()

    def _write_state_file(self, state: dict) -> None:
        """Write state to session_state.json atomically."""
        import tempfile

        SESSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file then rename (atomic on POSIX)
        temp_fd, temp_path = tempfile.mkstemp(suffix=".tmp", prefix="session_state_", dir=SESSION_STATE_FILE.parent)
        try:
            with os.fdopen(temp_fd, "w") as f:
                json.dump(state, f, indent=2, default=str)
            Path(temp_path).replace(SESSION_STATE_FILE)
        except Exception:
            try:
                Path(temp_path).unlink()
            except OSError:
                pass
            raise

    async def _watch_loop(self):
        """Watch for Cursor DB changes and trigger syncs."""
        logger.info("Starting watch loop")

        while not self._shutdown_event.is_set():
            try:
                # Check for state changes
                current_hash = self._compute_state_hash()

                if current_hash and current_hash != self._last_state_hash:
                    logger.info("Detected session state change, syncing...")
                    self._last_state_hash = current_hash

                    # Do sync
                    await self._do_sync()

                    # Emit D-Bus signal
                    self.emit_event("StateChanged", json.dumps({"type": "sessions_updated"}))

                    # Note: We don't emit toast notifications for session syncs
                    # as they happen frequently and would be noisy. The D-Bus signal
                    # is sufficient for the VS Code extension to update its UI.

                # Wait before next check
                await asyncio.sleep(self._watch_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Watch loop error: {e}")
                await asyncio.sleep(5)

    async def _periodic_sync_loop(self):
        """Periodic full sync regardless of detected changes."""
        logger.info(f"Starting periodic sync loop (interval: {self._sync_interval}s)")

        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self._sync_interval)

                if self._shutdown_event.is_set():
                    break

                # Force sync
                await self._do_sync()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Periodic sync error: {e}")
                await asyncio.sleep(5)

    async def run(self):
        """Main daemon run loop."""
        logger.info("Session daemon starting...")
        self.is_running = True
        self.start_time = time.time()

        # Load configuration
        self._load_configured_paths()

        # Initial sync
        logger.info("Running initial sync...")
        await self._do_sync()
        self._last_state_hash = self._compute_state_hash()

        # Start D-Bus if enabled
        if self.enable_dbus:
            await self.start_dbus()

        # Create tasks
        watch_task = asyncio.create_task(self._watch_loop())
        sync_task = asyncio.create_task(self._periodic_sync_loop())

        logger.info("Session daemon running")

        try:
            # Wait for shutdown
            await self._shutdown_event.wait()
        finally:
            # Cleanup
            watch_task.cancel()
            sync_task.cancel()

            try:
                await watch_task
            except asyncio.CancelledError:
                pass

            try:
                await sync_task
            except asyncio.CancelledError:
                pass

            if self.enable_dbus:
                await self.stop_dbus()

            self.is_running = False
            logger.info("Session daemon stopped")

    def shutdown(self):
        """Signal the daemon to shutdown."""
        logger.info("Shutdown requested")
        self._shutdown_event.set()


# ==================== CLI ====================


def check_status() -> int:
    """Check if daemon is running."""
    instance = SingleInstance()
    pid = instance.get_running_pid()

    if pid:
        print(f"Session daemon is running (PID: {pid})")
        return 0
    else:
        print("Session daemon is not running")
        return 1


def stop_daemon() -> int:
    """Stop the running daemon."""
    instance = SingleInstance()
    pid = instance.get_running_pid()

    if not pid:
        print("Session daemon is not running")
        return 1

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to PID {pid}")

        # Wait for process to exit
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except OSError:
                print("Session daemon stopped")
                return 0

        print("Daemon did not stop, sending SIGKILL")
        os.kill(pid, signal.SIGKILL)
        return 0

    except OSError as e:
        print(f"Failed to stop daemon: {e}")
        return 1


async def search_chats(query: str, limit: int = 20) -> int:
    """Search chats via D-Bus."""
    try:
        client = get_client("session")
    except ValueError:
        # Client not registered yet, add it
        from scripts.common.dbus_base import DaemonClient

        client = DaemonClient(
            service_name="com.aiworkflow.BotSession",
            object_path="/com/aiworkflow/BotSession",
            interface_name="com.aiworkflow.BotSession",
        )

    if not await client.connect():
        print("Failed to connect to session daemon. Is it running?")
        return 1

    try:
        result = await client.call_method("search_chats", [query, limit])
        await client.disconnect()

        if "error" in result:
            print(f"Search error: {result['error']}")
            return 1

        results = result.get("results", [])
        print(f"Found {len(results)} results for '{query}':\n")

        for r in results:
            print(f"  [{r['project']}] {r['name']}")
            if r.get("name_match"):
                print(f"    ✓ Name matches")
            if r.get("content_matches"):
                for m in r["content_matches"][:2]:
                    print(f"    → {m['snippet']}")
            print()

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Session Daemon - Cursor session state manager")
    parser.add_argument("--status", action="store_true", help="Check if daemon is running")
    parser.add_argument("--stop", action="store_true", help="Stop running daemon")
    parser.add_argument("--search", type=str, help="Search chats for query")
    parser.add_argument("--limit", type=int, default=20, help="Search result limit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--no-dbus", action="store_true", help="Disable D-Bus IPC")

    args = parser.parse_args()

    if args.status:
        sys.exit(check_status())

    if args.stop:
        sys.exit(stop_daemon())

    if args.search:
        sys.exit(asyncio.run(search_chats(args.search, args.limit)))

    # Run daemon
    instance = SingleInstance()
    if not instance.acquire():
        pid = instance.get_running_pid()
        print(f"Another instance is already running (PID: {pid})")
        sys.exit(1)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    daemon = SessionDaemon(verbose=args.verbose, enable_dbus=not args.no_dbus)

    # Setup signal handlers
    def signal_handler(signum, frame):
        daemon.shutdown()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        asyncio.run(daemon.run())
    finally:
        instance.release()


if __name__ == "__main__":
    main()
