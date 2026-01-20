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
- Buffers requests during restart (debounced)
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
    MCP_PROXY_NO_DAEMONS=1      Don't restart daemons on reload
"""

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
NO_DAEMONS = os.environ.get("MCP_PROXY_NO_DAEMONS", "").lower() in ("1", "true", "yes")

# Systemd user services to restart on reload
DAEMON_SERVICES = [
    "cron-scheduler.service",
    "slack-agent.service",
    "meet-bot.service",
]


def log(msg: str, force: bool = False):
    """Log to stderr (doesn't interfere with stdio protocol)."""
    if DEBUG or force:
        timestamp = time.strftime("%H:%M:%S")
        print(f"[mcp-proxy {timestamp}] {msg}", file=sys.stderr, flush=True)


def restart_daemons():
    """Restart dependent systemd user services."""
    if NO_DAEMONS:
        log("Daemon restart disabled")
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
    """Stdio-to-stdio proxy with file watching and hot reload."""

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

    def start_server(self, restart_daemons_too: bool = False) -> bool:
        """Start or restart the real MCP server. Returns True if successful."""
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

                # Replay any pending input
                if self.pending_input:
                    log(f"Replaying {len(self.pending_input)} pending message(s)")
                    for data in self.pending_input:
                        if self.process.stdin:
                            self.process.stdin.write(data)
                            self.process.stdin.flush()
                    self.pending_input.clear()

                return True
            except Exception as e:
                log(f"Failed to start server: {e}", force=True)
                return False

    def forward_stdin(self):
        """Forward Cursor's stdin to the real server's stdin."""
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

                    with self.restart_lock:
                        if self.process and self.process.poll() is None:
                            # Server is running, forward the message
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
                            log("Server not ready, queuing message")
                            self.pending_input.append(message)

            except Exception as e:
                if not self.shutting_down:
                    log(f"stdin error: {e}")
                break

        log("stdin forwarder stopped")

    def forward_stdout(self):
        """Forward real server's stdout to Cursor's stdout."""
        log("stdout forwarder started")

        while not self.shutting_down:
            # Get current process reference
            with self.restart_lock:
                proc = self.process

            if not proc or proc.poll() is not None:
                # No process or process died, wait a bit
                time.sleep(0.05)
                continue

            try:
                # Read from server's stdout
                if proc.stdout:
                    data = proc.stdout.read(4096)
                    if data:
                        # Forward to Cursor's stdout
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                        log(f"← Forwarded {len(data)} bytes to Cursor")
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
                # Directory watch - find all matching files
                for ext in WATCH_EXTENSIONS:
                    try:
                        for f in watch_path.rglob(f"*{ext}"):
                            # Skip node_modules and other common excludes
                            if "node_modules" in f.parts:
                                continue
                            if "__pycache__" in f.parts:
                                continue
                            if ".git" in f.parts:
                                continue
                            try:
                                mtimes[f] = f.stat().st_mtime
                            except OSError:
                                pass
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
                log("Server reloaded ✓", force=True)

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
            elif proxy_args[i] == "--no-daemons":
                global NO_DAEMONS
                NO_DAEMONS = True
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
        print("  --no-daemons      Don't restart daemons on reload", file=sys.stderr)
        print("", file=sys.stderr)
        print("Example:", file=sys.stderr)
        print("  mcp_proxy.py --cwd /path/to/project -- uv run python -m server", file=sys.stderr)
        print("", file=sys.stderr)
        print("Environment variables:", file=sys.stderr)
        print("  MCP_PROXY_DEBUG=1           Enable debug logging", file=sys.stderr)
        print("  MCP_PROXY_NO_WATCH=1        Disable file watching", file=sys.stderr)
        print("  MCP_PROXY_NO_DAEMONS=1      Don't restart daemons", file=sys.stderr)
        print("  MCP_PROXY_DEBOUNCE=3.0      Debounce time in seconds", file=sys.stderr)
        sys.exit(1)

    log(f"Working directory: {working_dir}", force=True)
    log(f"Server command: {' '.join(server_cmd)}", force=True)
    log(f"Watch paths: {len(watch_paths)} directories/files", force=True)
    log(f"Debounce: {DEBOUNCE_SECONDS}s", force=True)
    log(f"Daemon restart: {'disabled' if NO_DAEMONS else 'enabled'}", force=True)

    proxy = HotReloadProxy(server_cmd, watch_paths, working_dir)
    proxy.run()


if __name__ == "__main__":
    main()
