#!/usr/bin/env python3
"""
MCP Hot-Reload Proxy

Transparent stdio-to-stdio proxy that allows hot-reloading the real MCP server
without Cursor knowing. Neither Cursor nor the real server knows about this layer.

Architecture:
    ┌─────────┐  stdio   ┌─────────────┐  stdio   ┌─────────────┐
    │ Cursor  │ ◄──────► │   Proxy     │ ◄──────► │ Real MCP    │
    │         │          │ (spawns &   │          │ Server      │
    └─────────┘          │  restarts)  │          └─────────────┘
                         └─────────────┘

Features:
- Spawns the real MCP server as a subprocess
- Forwards stdin/stdout bidirectionally
- Watches for file changes and restarts the subprocess
- Restarts dependent daemons (cron, slack, meet) on reload
- Handles MCP protocol initialization on restart (waits for re-init)
- Sends tools/list_changed notification to trigger Cursor refresh
- Transparent to both Cursor and the real server

Usage in mcp.json (with proxy):
    {
        "mcpServers": {
            "aa_workflow": {
                "command": "python",
                "args": [
                    "/path/to/scripts/mcp_proxy.py",
                    "--cwd", "/path/to/redhat-ai-workflow",
                    "--",
                    "uv", "run", "python", "-m", "server"
                ]
            }
        }
    }

To remove proxy (direct connection):
    {
        "mcpServers": {
            "aa_workflow": {
                "command": "uv",
                "args": ["run", "--directory", "/path/to/redhat-ai-workflow", "python", "-m", "server"]
            }
        }
    }

Environment variables:
    MCP_PROXY_DEBUG=1           Enable debug logging
    MCP_PROXY_NO_WATCH=1        Disable file watching (just proxy)
    MCP_PROXY_DEBOUNCE=3.0      Debounce time in seconds (default: 3.0)
    MCP_PROXY_RESTART_DAEMONS=1 Restart daemons on reload (disabled by default)
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

# Configuration - watch all important project directories
# NOTE: Don't include memory/ - it's written to during skill execution
DEFAULT_WATCH_PATHS = [
    # Python backend
    "server/",
    "tool_modules/",
    "scripts/",
    "ptools/",
    # Configuration and data
    "skills/",
    "personas/",
    # VSCode extension
    "extensions/aa_workflow_vscode/src/",
    # Root config files
    "config.json",
    ".flake8",
    ".pre-commit-config.yaml",
]

# File extensions to watch
WATCH_EXTENSIONS = {
    ".py",  # Python
    ".ts",  # TypeScript (VSCode extension)
    ".js",  # JavaScript
    ".json",  # Config files
    ".yaml",  # Skills, personas, memory
    ".yml",  # Alternative YAML extension
    ".toml",  # pyproject.toml etc
}

# Debounce: 3 seconds to allow batch saves and avoid rapid restarts
DEBOUNCE_SECONDS = float(os.environ.get("MCP_PROXY_DEBOUNCE", "3.0"))

# Debug and feature flags
DEBUG = os.environ.get("MCP_PROXY_DEBUG", "").lower() in ("1", "true", "yes")
NO_WATCH = os.environ.get("MCP_PROXY_NO_WATCH", "").lower() in ("1", "true", "yes")
# NO_DAEMONS is now True by default - daemons run independently and don't need restart
# Set MCP_PROXY_RESTART_DAEMONS=1 to re-enable daemon restarts
NO_DAEMONS = os.environ.get("MCP_PROXY_RESTART_DAEMONS", "").lower() not in ("1", "true", "yes")

# Systemd user services to restart on reload
# NOTE: These are now DISABLED by default. The daemons (cron, slack, meet) run
# independently and don't need to restart when the MCP server restarts.
# Restarting them was causing duplicate scheduler instances and job execution.
# Set MCP_PROXY_RESTART_DAEMONS=1 to re-enable if needed.
DAEMON_SERVICES: list[str] = [
    # "cron-scheduler.service",  # Disabled - runs independently, has its own config watcher
    # "slack-agent.service",     # Disabled - runs independently
    # "meet-bot.service",        # Disabled - runs independently
]


def log(msg: str, force: bool = False):
    """Log to stderr (doesn't interfere with stdio protocol)."""
    if DEBUG or force:
        timestamp = time.strftime("%H:%M:%S")
        print(f"[mcp-proxy {timestamp}] {msg}", file=sys.stderr, flush=True)


def restart_daemons():
    """Restart dependent systemd user services.

    NOTE: This is now disabled by default. The daemons (cron-scheduler, slack-agent,
    meet-bot) run independently of the MCP server and have their own config watchers.
    Restarting them on MCP reload was causing duplicate scheduler instances.

    Set MCP_PROXY_RESTART_DAEMONS=1 to re-enable if needed.
    """
    if NO_DAEMONS:
        log("Daemon restart disabled (daemons run independently)")
        return

    if not DAEMON_SERVICES:
        log("No daemon services configured for restart")
        return

    for service in DAEMON_SERVICES:
        try:
            # Check if service is active before trying to restart
            result = subprocess.run(
                ["systemctl", "--user", "is-active", service],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Service is active, restart it
                log(f"Restarting {service}...", force=True)
                subprocess.run(
                    ["systemctl", "--user", "restart", service],
                    capture_output=True,
                    timeout=10,
                )
                log(f"  ✓ {service} restarted", force=True)
            else:
                log(f"  - {service} not running, skipping")
        except subprocess.TimeoutExpired:
            log(f"  ⚠ {service} restart timed out")
        except FileNotFoundError:
            # systemctl not available
            log("systemctl not found, skipping daemon restarts")
            break
        except Exception as e:
            log(f"  ⚠ {service} restart failed: {e}")


class HotReloadProxy:
    """Stdio-to-stdio proxy with file watching and hot reload.

    Handles MCP protocol initialization properly on restart:
    - Discards stale pending messages from old session
    - Waits for Cursor to re-initialize with new server
    - Sends tools/list_changed notification to trigger Cursor refresh
    """

    def __init__(self, server_cmd: list[str], watch_paths: list[str], working_dir: str):
        self.server_cmd = server_cmd
        self.watch_paths = [Path(working_dir) / p for p in watch_paths]
        self.working_dir = working_dir
        self.process: subprocess.Popen | None = None
        self.restart_lock = threading.Lock()
        self.pending_input: list[bytes] = []
        self.shutting_down = False
        self.last_mtimes: dict[Path, float] = {}
        self.restart_count = 0

        # MCP session state tracking
        self.session_initialized = False
        self.awaiting_reinit = False  # True after restart, waiting for new initialize
        self.stdout_lock = threading.Lock()  # Protect stdout writes

        # Cache the last initialize request so we can replay it on restart
        self.cached_initialize_request: bytes | None = None

    def _send_to_cursor(self, message: dict) -> None:
        """Send a JSON-RPC message to Cursor (thread-safe)."""
        with self.stdout_lock:
            try:
                data = json.dumps(message) + "\n"
                sys.stdout.buffer.write(data.encode())
                sys.stdout.buffer.flush()
                log(f"← Sent to Cursor: {message.get('method', 'response')}")
            except Exception as e:
                log(f"Failed to send to Cursor: {e}")

    def _notify_tools_changed(self) -> None:
        """Send tools/list_changed notification to Cursor.

        This tells Cursor that tools have changed and it should refresh.
        Cursor will then send a new tools/list request.
        """
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/tools/list_changed",
        }
        self._send_to_cursor(notification)
        log("Sent tools/list_changed notification to Cursor", force=True)

    def start_server(self, restart_daemons_too: bool = False) -> bool:
        """Start or restart the real MCP server. Returns True if successful."""
        is_restart = self.process is not None

        with self.restart_lock:
            # Kill existing process if any
            if self.process:
                log("Stopping server for reload...")
                try:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        log("Server didn't terminate, killing...")
                        self.process.kill()
                        self.process.wait()
                except Exception as e:
                    log(f"Error stopping server: {e}")

            # Restart daemons if requested (only on file-change triggered restarts)
            if restart_daemons_too:
                restart_daemons()

            # Start new process
            log(f"Starting server: {' '.join(self.server_cmd)}")
            try:
                self.process = subprocess.Popen(
                    self.server_cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=sys.stderr,  # Pass through stderr for debugging
                    cwd=self.working_dir,
                    bufsize=0,  # Unbuffered
                )
                self.restart_count += 1
                log(f"Server started (PID: {self.process.pid}, restart #{self.restart_count})")

                # On restart: discard stale pending messages and re-initialize
                # The old session's messages would fail with "not initialized" error
                if is_restart:
                    if self.pending_input:
                        log(f"Discarding {len(self.pending_input)} stale message(s) from old session", force=True)
                        self.pending_input.clear()

                    # Reset session state
                    self.session_initialized = False

                    # Replay the cached initialize request to the new server
                    # This re-establishes the MCP session transparently
                    if self.cached_initialize_request and self.process.stdin:
                        log("Replaying cached initialize request to new server", force=True)
                        try:
                            self.process.stdin.write(self.cached_initialize_request)
                            self.process.stdin.flush()
                            self.awaiting_reinit = False  # We've sent init, just waiting for response
                            log("Initialize request sent to new server ✓", force=True)
                        except OSError as e:
                            log(f"Failed to replay initialize: {e}", force=True)
                            self.awaiting_reinit = True
                    else:
                        # No cached request, need Cursor to re-initialize
                        self.awaiting_reinit = True
                        log("No cached initialize request, awaiting re-init from Cursor", force=True)
                else:
                    # Initial start - session not yet initialized
                    self.session_initialized = False
                    self.awaiting_reinit = False

                return True
            except Exception as e:
                log(f"Failed to start server: {e}", force=True)
                return False

    def _parse_jsonrpc_method(self, data: bytes) -> tuple[str | None, int | str | None]:
        """Parse JSON-RPC message to extract method and id.

        Returns:
            (method, id) tuple. method is None for responses.
        """
        try:
            msg = json.loads(data.decode())
            return msg.get("method"), msg.get("id")
        except Exception:
            return None, None

    def _is_initialize_request(self, data: bytes) -> bool:
        """Check if this is an MCP initialize request."""
        method, _ = self._parse_jsonrpc_method(data)
        return method == "initialize"

    def _is_initialized_notification(self, data: bytes) -> bool:
        """Check if this is an MCP initialized notification."""
        method, _ = self._parse_jsonrpc_method(data)
        return method == "notifications/initialized"

    def _is_safe_during_reinit(self, data: bytes) -> bool:
        """Check if this request is safe to forward during re-initialization.

        Some requests like tools/list, resources/list, prompts/list are safe
        because they're triggered by our tools/list_changed notification and
        don't require a fully initialized session on the new server.
        """
        method, _ = self._parse_jsonrpc_method(data)
        # These are "list" requests that Cursor sends in response to changed notifications
        # They work even without full initialization
        safe_methods = {
            "initialize",
            "tools/list",
            "resources/list",
            "prompts/list",
            "ping",
        }
        return method in safe_methods

    def forward_stdin(self):
        """Forward Cursor's stdin to the real server's stdin.

        Handles MCP protocol state:
        - Tracks initialize/initialized sequence
        - After restart, waits for re-initialization before forwarding other requests
        - Queues messages during server restart
        """
        log("stdin forwarder started")
        buffer = b""

        while not self.shutting_down:
            try:
                # Read from Cursor's stdin
                # Use os.read for non-blocking-ish reads
                data = os.read(sys.stdin.fileno(), 4096)
                if not data:
                    log("stdin closed (Cursor disconnected)")
                    break

                buffer += data

                # Process complete lines (JSON-RPC messages are newline-delimited)
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    message = line + b"\n"

                    # Parse the message to understand MCP protocol state
                    is_init_request = self._is_initialize_request(line)
                    is_init_notification = self._is_initialized_notification(line)

                    if is_init_request:
                        log("→ Received initialize request from Cursor")
                        self.awaiting_reinit = False  # Got the re-init we were waiting for
                        # Cache this for replay on future restarts
                        self.cached_initialize_request = message
                        log("Cached initialize request for future restarts")

                    if is_init_notification:
                        log("→ Received initialized notification from Cursor")
                        self.session_initialized = True
                        log("MCP session initialized ✓", force=True)

                    with self.restart_lock:
                        if self.process and self.process.poll() is None:
                            # Server is running

                            # Check if this request is safe during re-init
                            is_safe = self._is_safe_during_reinit(line)

                            # If we're awaiting re-init after restart, only allow
                            # safe requests through (initialize, tools/list, etc.)
                            if self.awaiting_reinit and not is_safe:
                                method, msg_id = self._parse_jsonrpc_method(line)
                                if method:
                                    log(f"⏳ Dropping {method} (awaiting re-initialization)", force=True)
                                    # Send error response if it has an id (is a request)
                                    if msg_id is not None:
                                        error_response = {
                                            "jsonrpc": "2.0",
                                            "id": msg_id,
                                            "error": {"code": -32002, "message": "Server restarting, please retry"},
                                        }
                                        self._send_to_cursor(error_response)
                                continue

                            # If we got a safe request during reinit, clear the flag
                            # since Cursor is clearly communicating with us
                            if self.awaiting_reinit and is_safe:
                                method, _ = self._parse_jsonrpc_method(line)
                                log(f"✓ Received {method} during reinit - connection restored", force=True)
                                self.awaiting_reinit = False

                            # Forward the message
                            try:
                                if self.process.stdin:
                                    self.process.stdin.write(message)
                                    self.process.stdin.flush()
                                    log(f"→ Forwarded {len(message)} bytes to server")
                            except OSError as e:
                                log(f"Server stdin broken: {e}, queuing message")
                                self.pending_input.append(message)
                        else:
                            # Server is restarting, queue the message
                            # But only queue initialize requests - others are stale
                            if is_init_request:
                                log("Server not ready, queuing initialize request")
                                self.pending_input.append(message)
                            else:
                                method, _ = self._parse_jsonrpc_method(line)
                                log(f"Server not ready, dropping {method or 'message'}")

            except Exception as e:
                if not self.shutting_down:
                    log(f"stdin error: {e}")
                break

        log("stdin forwarder stopped")

    def forward_stdout(self):
        """Forward real server's stdout to Cursor's stdout.

        Also monitors for initialization response to send tools_changed notification.
        """
        log("stdout forwarder started")
        buffer = b""
        sent_tools_changed_for_restart = 0  # Track which restart we sent notification for

        while not self.shutting_down:
            # Get current process reference
            with self.restart_lock:
                proc = self.process
                current_restart = self.restart_count

            if not proc or proc.poll() is not None:
                # No process or process died, wait a bit
                time.sleep(0.05)
                continue

            try:
                # Read from server's stdout
                if proc.stdout:
                    data = proc.stdout.read(4096)
                    if data:
                        buffer += data

                        # Process complete lines to detect initialization response
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)

                            # Check if this is a response to initialize request
                            # (contains "result" with "serverInfo" or "capabilities")
                            try:
                                msg = json.loads(line.decode())
                                if "result" in msg and isinstance(msg.get("result"), dict):
                                    result = msg["result"]
                                    if "serverInfo" in result or "capabilities" in result:
                                        log("← Server sent initialize response")

                                        # After restart, we replayed the cached initialize request
                                        # Don't forward this response to Cursor (it didn't send the request)
                                        # Instead, send the initialized notification to complete handshake
                                        # Then send tools_changed to trigger Cursor to refresh
                                        if current_restart > 1 and sent_tools_changed_for_restart < current_restart:
                                            sent_tools_changed_for_restart = current_restart

                                            # Send initialized notification to server to complete handshake
                                            initialized_notification = {
                                                "jsonrpc": "2.0",
                                                "method": "notifications/initialized",
                                            }
                                            try:
                                                init_data = json.dumps(initialized_notification) + "\n"
                                                if self.process and self.process.stdin:
                                                    self.process.stdin.write(init_data.encode())
                                                    self.process.stdin.flush()
                                                    log("→ Sent initialized notification to server")
                                                    self.session_initialized = True
                                            except OSError as e:
                                                log(f"Failed to send initialized notification: {e}")

                                            # Small delay then send tools_changed to Cursor
                                            time.sleep(0.1)
                                            self._notify_tools_changed()

                                            # Don't forward the init response to Cursor
                                            continue
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                pass  # Not valid JSON, just forward it

                            # Forward to Cursor's stdout
                            with self.stdout_lock:
                                sys.stdout.buffer.write(line + b"\n")
                                sys.stdout.buffer.flush()
                            log(f"← Forwarded {len(line) + 1} bytes to Cursor")

                    elif proc.poll() is not None:
                        # Process died and no more data
                        log("Server process ended")
                        time.sleep(0.1)
            except Exception as e:
                if not self.shutting_down:
                    log(f"stdout error: {e}")
                time.sleep(0.1)

        log("stdout forwarder stopped")

    def get_file_mtimes(self) -> dict[Path, float]:
        """Get modification times of all watched files."""
        # Directories to skip entirely (don't even traverse into them)
        skip_dirs = {
            "node_modules",
            "__pycache__",
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            ".tox",
            "dist",
            "build",
            ".eggs",
        }

        mtimes = {}
        for watch_path in self.watch_paths:
            if not watch_path.exists():
                continue
            if watch_path.is_file():
                # Direct file watch (e.g., config.json)
                try:
                    if watch_path.suffix in WATCH_EXTENSIONS:
                        mtimes[watch_path] = watch_path.stat().st_mtime
                except OSError:
                    pass
            else:
                # Directory watch - use os.walk with directory pruning
                # This is MUCH faster than rglob because we skip entire subtrees
                for dirpath, dirnames, filenames in os.walk(watch_path):
                    # Prune directories IN PLACE to prevent descending into them
                    # This is the key optimization - we never even open these dirs
                    dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.endswith(".egg-info")]

                    # Check files in this directory
                    for filename in filenames:
                        filepath = Path(dirpath) / filename
                        if filepath.suffix in WATCH_EXTENSIONS:
                            try:
                                mtimes[filepath] = filepath.stat().st_mtime
                            except OSError:
                                pass
        return mtimes

    def watch_files(self):
        """Poll for file changes and restart server when detected."""
        if NO_WATCH:
            log("File watching disabled")
            return

        log(f"File watcher started (watching {len(self.watch_paths)} paths)")
        self.last_mtimes = self.get_file_mtimes()
        log(f"Tracking {len(self.last_mtimes)} files")
        log(f"Debounce: {DEBOUNCE_SECONDS}s")

        last_change_time = 0.0
        needs_restart = False
        changed_files_batch: list[tuple[str, Path]] = []

        while not self.shutting_down:
            time.sleep(0.5)  # Poll every 500ms

            current_mtimes = self.get_file_mtimes()

            # Check for changes
            changed_files = []

            # Check modified files
            for path, mtime in current_mtimes.items():
                if path not in self.last_mtimes:
                    changed_files.append(("new", path))
                elif self.last_mtimes[path] != mtime:
                    changed_files.append(("modified", path))

            # Check deleted files
            for path in self.last_mtimes:
                if path not in current_mtimes:
                    changed_files.append(("deleted", path))

            if changed_files:
                for change_type, f in changed_files:
                    try:
                        rel_path = f.relative_to(self.working_dir)
                    except ValueError:
                        rel_path = f
                    log(f"File {change_type}: {rel_path}", force=True)
                    changed_files_batch.append((change_type, f))
                last_change_time = time.time()
                needs_restart = True
                self.last_mtimes = current_mtimes

            # Debounce: restart after DEBOUNCE_SECONDS of no changes
            if needs_restart and (time.time() - last_change_time) > DEBOUNCE_SECONDS:
                log(f"Reloading after {len(changed_files_batch)} file change(s)...", force=True)
                self.start_server(restart_daemons_too=True)
                needs_restart = False
                changed_files_batch.clear()

                # Give server a moment to start and be ready for initialize
                time.sleep(0.5)

                # Send tools_changed notification to prompt Cursor to refresh
                # Note: This only works if Cursor has an active session.
                # If the session is broken, Cursor may need to be manually refreshed.
                self._notify_tools_changed()

                log("Server reloaded ✓ - Cursor may need manual refresh if tools don't appear", force=True)

        log("File watcher stopped")

    def run(self):
        """Main entry point - start proxy and run until shutdown."""

        # Set up signal handlers
        def shutdown(sig, frame):
            log(f"Received signal {sig}, shutting down...")
            self.shutting_down = True
            if self.process:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=5)
                except Exception:
                    if self.process:
                        self.process.kill()
            sys.exit(0)

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)

        # Start the real server (don't restart daemons on initial start)
        if not self.start_server(restart_daemons_too=False):
            log("Failed to start server, exiting", force=True)
            sys.exit(1)

        # Start forwarding threads
        stdin_thread = threading.Thread(target=self.forward_stdin, name="stdin-forwarder", daemon=True)
        stdout_thread = threading.Thread(target=self.forward_stdout, name="stdout-forwarder", daemon=True)
        watch_thread = threading.Thread(target=self.watch_files, name="file-watcher", daemon=True)

        stdin_thread.start()
        stdout_thread.start()
        watch_thread.start()

        log("Proxy running")

        # Wait for stdin to close (Cursor disconnected)
        stdin_thread.join()

        log("Shutting down...")
        self.shutting_down = True

        # Clean up
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                if self.process:
                    self.process.kill()

        log("Proxy stopped")


def main():
    """Parse arguments and start the proxy."""
    args = sys.argv[1:]

    # Handle help before anything else
    if not args or "--help" in args or "-h" in args:
        print(__doc__)
        sys.exit(0)

    watch_paths = list(DEFAULT_WATCH_PATHS)
    working_dir = os.getcwd()

    # Find the -- separator
    if "--" in args:
        sep_idx = args.index("--")
        proxy_args = args[:sep_idx]
        server_cmd = args[sep_idx + 1 :]

        # Parse proxy args
        i = 0
        while i < len(proxy_args):
            if proxy_args[i] == "--watch" and i + 1 < len(proxy_args):
                watch_paths.append(proxy_args[i + 1])
                i += 2
            elif proxy_args[i] == "--cwd" and i + 1 < len(proxy_args):
                working_dir = proxy_args[i + 1]
                i += 2
            elif proxy_args[i] == "--debounce" and i + 1 < len(proxy_args):
                global DEBOUNCE_SECONDS
                DEBOUNCE_SECONDS = float(proxy_args[i + 1])
                i += 2
            elif proxy_args[i] == "--debug":
                global DEBUG
                DEBUG = True
                i += 1
            elif proxy_args[i] == "--no-watch":
                global NO_WATCH
                NO_WATCH = True
                i += 1
            elif proxy_args[i] == "--restart-daemons":
                global NO_DAEMONS
                NO_DAEMONS = False  # Enable daemon restarts
                i += 1
            elif proxy_args[i] == "--no-daemons":
                # Legacy flag, now the default behavior
                i += 1
            elif proxy_args[i] in ("--help", "-h"):
                print(__doc__)
                sys.exit(0)
            else:
                print(f"Unknown option: {proxy_args[i]}", file=sys.stderr)
                i += 1
    else:
        server_cmd = args

    if not server_cmd:
        print("Usage: mcp_proxy.py [OPTIONS] -- <server command>", file=sys.stderr)
        print("", file=sys.stderr)
        print("Options:", file=sys.stderr)
        print("  --cwd DIR         Working directory for server (default: current)", file=sys.stderr)
        print("  --watch PATH      Additional path to watch (can be repeated)", file=sys.stderr)
        print("  --debounce SECS   Debounce time in seconds (default: 3.0)", file=sys.stderr)
        print("  --debug           Enable debug logging", file=sys.stderr)
        print("  --no-watch        Disable file watching", file=sys.stderr)
        print("  --restart-daemons Restart daemons on reload (disabled by default)", file=sys.stderr)
        print("", file=sys.stderr)
        print("Example:", file=sys.stderr)
        print("  mcp_proxy.py --cwd /path/to/project -- uv run python -m server", file=sys.stderr)
        print("", file=sys.stderr)
        print("Environment variables:", file=sys.stderr)
        print("  MCP_PROXY_DEBUG=1           Enable debug logging", file=sys.stderr)
        print("  MCP_PROXY_NO_WATCH=1        Disable file watching", file=sys.stderr)
        print("  MCP_PROXY_RESTART_DAEMONS=1 Restart daemons on reload (disabled by default)", file=sys.stderr)
        print("  MCP_PROXY_DEBOUNCE=3.0      Debounce time in seconds", file=sys.stderr)
        sys.exit(1)

    log(f"Working directory: {working_dir}", force=True)
    log(f"Server command: {' '.join(server_cmd)}", force=True)
    log(f"Watch paths: {len(watch_paths)} directories/files", force=True)
    log(f"Debounce: {DEBOUNCE_SECONDS}s", force=True)
    log(f"Daemon restart: {'disabled (default)' if NO_DAEMONS else 'enabled'}", force=True)

    proxy = HotReloadProxy(server_cmd, watch_paths, working_dir)
    proxy.run()


if __name__ == "__main__":
    main()
