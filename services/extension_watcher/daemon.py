#!/usr/bin/env python3
"""
VSCode Extension Hot-Reload Watcher

Watches the VSCode extension source files, recompiles on changes,
and notifies you to reload the Cursor window.

Unlike the MCP backend which can be restarted transparently, VSCode
extensions require a window reload to pick up changes.

Usage:
    python scripts/extension_watcher.py           # Watch and compile
    python scripts/extension_watcher.py --notify  # Also send desktop notification

The watcher:
1. Monitors extensions/aa_workflow_vscode/src/*.ts for changes
2. Runs `npm run compile` on change (debounced)
3. Shows a desktop notification to reload Cursor

To reload Cursor after compilation:
    Cmd+Shift+P → "Developer: Reload Window"
    Or: Ctrl+Shift+P → "Developer: Reload Window"
"""

import os
import subprocess
import sys
import time
from pathlib import Path

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent.parent
EXTENSION_DIR = PROJECT_ROOT / "extensions" / "aa_workflow_vscode"
EXTENSION_SRC = EXTENSION_DIR / "src"
WATCH_EXTENSIONS = {".ts", ".json"}
DEBOUNCE_SECONDS = 2.0
ENABLE_NOTIFY = "--notify" in sys.argv or os.environ.get("EXTENSION_WATCHER_NOTIFY", "").lower() in ("1", "true")


def log(msg: str):
    """Log with timestamp."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[ext-watcher {timestamp}] {msg}", flush=True)


def send_notification(title: str, message: str):
    """Send a desktop notification."""
    if not ENABLE_NOTIFY:
        return

    try:
        # Try notify-send (Linux)
        subprocess.run(
            ["notify-send", "-u", "normal", "-t", "5000", title, message],
            capture_output=True,
            timeout=5,
        )
    except FileNotFoundError:
        # notify-send not available
        pass
    except Exception as e:
        log(f"Notification failed: {e}")


def compile_extension() -> bool:
    """Run npm compile and return success status."""
    log("Compiling extension...")
    try:
        result = subprocess.run(
            ["npm", "run", "compile"],
            cwd=EXTENSION_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            log("✓ Compilation successful")
            return True
        else:
            log(f"✗ Compilation failed:\n{result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        log("✗ Compilation timed out")
        return False
    except Exception as e:
        log(f"✗ Compilation error: {e}")
        return False


def get_file_mtimes() -> dict[Path, float]:
    """Get modification times of watched files."""
    mtimes = {}

    # Watch src/*.ts files
    for ext in WATCH_EXTENSIONS:
        for f in EXTENSION_SRC.rglob(f"*{ext}"):
            try:
                mtimes[f] = f.stat().st_mtime
            except OSError:
                pass

    # Also watch package.json
    package_json = EXTENSION_DIR / "package.json"
    if package_json.exists():
        try:
            mtimes[package_json] = package_json.stat().st_mtime
        except OSError:
            pass

    return mtimes


def main():
    """Main watcher loop."""
    log(f"Watching: {EXTENSION_SRC}")
    log(f"Debounce: {DEBOUNCE_SECONDS}s")
    log(f"Notifications: {'enabled' if ENABLE_NOTIFY else 'disabled'}")
    log("")
    log("Press Ctrl+C to stop")
    log("-" * 40)

    last_mtimes = get_file_mtimes()
    log(f"Tracking {len(last_mtimes)} files")

    last_change_time = 0.0
    needs_compile = False
    changed_files: list[Path] = []

    try:
        while True:
            time.sleep(0.5)

            current_mtimes = get_file_mtimes()

            # Check for changes
            new_changed = []
            for path, mtime in current_mtimes.items():
                if path not in last_mtimes or last_mtimes[path] != mtime:
                    new_changed.append(path)

            if new_changed:
                for f in new_changed:
                    rel_path = f.relative_to(PROJECT_ROOT)
                    log(f"Changed: {rel_path}")
                    changed_files.append(f)
                last_change_time = time.time()
                needs_compile = True
                last_mtimes = current_mtimes

            # Debounce: compile after DEBOUNCE_SECONDS of no changes
            if needs_compile and (time.time() - last_change_time) > DEBOUNCE_SECONDS:
                log(f"Compiling after {len(changed_files)} file change(s)...")
                success = compile_extension()

                if success:
                    send_notification(
                        "Extension Recompiled",
                        "Reload Cursor window to apply changes\n(Cmd+Shift+P → Reload Window)",
                    )
                    log("")
                    log("╔════════════════════════════════════════════╗")
                    log("║  Extension recompiled! Reload Cursor:      ║")
                    log("║  Cmd+Shift+P → 'Developer: Reload Window'  ║")
                    log("╚════════════════════════════════════════════╝")
                    log("")
                else:
                    send_notification("Extension Compile Failed", "Check terminal for errors")

                needs_compile = False
                changed_files.clear()

    except KeyboardInterrupt:
        log("\nStopped")


if __name__ == "__main__":
    main()
