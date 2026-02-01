#!/usr/bin/env python3
"""
Slop Bot Service Entry Point.

Usage:
    python -m services.slop [options]

Options:
    --status          Check if daemon is running
    --stop            Stop running daemon
    -v, --verbose     Enable verbose output
    --dbus            Enable D-Bus IPC interface
    --no-dbus         Disable D-Bus IPC interface
    --max-parallel N  Maximum concurrent analysis loops (default: 3)
    --codebase PATH   Path to codebase to analyze
    --db-path PATH    Path to SQLite database
    --backend NAME    Preferred LLM backend (claude, gemini, codex, opencode)

Examples:
    # Start with D-Bus enabled
    python -m services.slop --dbus

    # Start with custom settings
    python -m services.slop --dbus --max-parallel 5 --backend claude

    # Check status
    python -m services.slop --status

    # Stop daemon
    python -m services.slop --stop
"""

from services.slop.daemon import SlopDaemon

if __name__ == "__main__":
    SlopDaemon.main()
