#!/usr/bin/env python3
"""
Ralph Wiggum Stop Hook for Cursor IDE

This script implements the stop hook pattern for autonomous task loops in Cursor.
It intercepts when Cursor's agent tries to stop and decides whether to continue
based on TODO.md completion status.

Session-aware: Each Cursor chat session has its own loop configuration,
allowing multiple concurrent loops without interference.

Usage:
    Configure in .cursor/hooks.json:
    {
      "version": 1,
      "hooks": {
        "stop": [{"command": "python ~/.config/aa-workflow/ralph_wiggum_hook.py"}]
      }
    }

Input (via stdin):
    JSON with session_id, stop_hook_active, cwd, etc.

Output:
    JSON with decision to block or allow stop
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def load_loop_config(session_id: str) -> dict | None:
    """Load the loop configuration for a specific session."""
    loops_dir = Path.home() / ".config" / "aa-workflow" / "ralph_loops"
    config_path = loops_dir / f"session_{session_id}.json"

    if not config_path.exists():
        return None

    try:
        return json.loads(config_path.read_text())
    except (json.JSONDecodeError, IOError):
        return None


def save_loop_config(session_id: str, config: dict) -> None:
    """Save the loop configuration for a specific session."""
    loops_dir = Path.home() / ".config" / "aa-workflow" / "ralph_loops"
    loops_dir.mkdir(parents=True, exist_ok=True)

    config_path = loops_dir / f"session_{session_id}.json"
    config_path.write_text(json.dumps(config, indent=2))


def delete_loop_config(session_id: str) -> None:
    """Delete the loop configuration (cleanup after completion)."""
    loops_dir = Path.home() / ".config" / "aa-workflow" / "ralph_loops"
    config_path = loops_dir / f"session_{session_id}.json"

    if config_path.exists():
        config_path.unlink()


def parse_todo_file(todo_path: Path) -> tuple[int, int, bool]:
    """
    Parse a TODO.md file and return task counts.

    Returns:
        (incomplete_count, complete_count, has_hard_stop)
    """
    if not todo_path.exists():
        return 0, 0, False

    content = todo_path.read_text()

    # Check for HARD STOP marker
    has_hard_stop = "**HARD STOP**" in content

    # Count tasks
    incomplete = content.count("- [ ]")
    complete = content.count("- [x]") + content.count("- [X]")

    return incomplete, complete, has_hard_stop


def check_completion_criteria(content: str, criteria: list[str]) -> bool:
    """Check if any completion criteria are met in the content."""
    content_lower = content.lower()
    for criterion in criteria:
        if criterion.lower() in content_lower:
            return True
    return False


def main():
    # Read input from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        # No valid input, allow stop
        sys.exit(0)

    # Extract relevant fields
    session_id = input_data.get("session_id", "unknown")
    stop_hook_active = input_data.get("stop_hook_active", False)
    cwd = input_data.get("cwd", ".")

    # Load session-specific loop config
    config = load_loop_config(session_id)

    # If no config for this session, it's not a Ralph loop - allow stop
    if config is None:
        sys.exit(0)

    # Extract config values
    max_iterations = config.get("max_iterations", 10)
    current_iteration = config.get("current_iteration", 0)
    todo_path_str = config.get("todo_path", str(Path(cwd) / "TODO.md"))
    completion_criteria = config.get("completion_criteria", [])

    # Check iteration limit
    if current_iteration >= max_iterations:
        # Hit limit, clean up and allow stop
        delete_loop_config(session_id)
        sys.exit(0)

    # Parse TODO.md
    todo_path = Path(todo_path_str)
    incomplete, complete, has_hard_stop = parse_todo_file(todo_path)

    # If no TODO file exists, clean up and allow stop
    if not todo_path.exists():
        delete_loop_config(session_id)
        sys.exit(0)

    # Check for HARD STOP marker (manual verification needed)
    if has_hard_stop:
        # Don't delete config - user may want to resume after verification
        sys.exit(0)

    # Check completion criteria
    if completion_criteria:
        content = todo_path.read_text()
        if check_completion_criteria(content, completion_criteria):
            delete_loop_config(session_id)
            sys.exit(0)

    # If there are incomplete tasks and we're not already in a loop, continue
    if incomplete > 0 and not stop_hook_active:
        # Update iteration count
        config["current_iteration"] = current_iteration + 1
        config["last_updated"] = datetime.now().isoformat()
        save_loop_config(session_id, config)

        # Build the continuation message
        total_tasks = incomplete + complete
        progress_pct = round((complete / total_tasks) * 100) if total_tasks > 0 else 0

        output = {
            "decision": "block",
            "reason": (
                f"[Ralph Wiggum Loop {current_iteration + 1}/{max_iterations}] "
                f"{incomplete} tasks remaining ({progress_pct}% complete). "
                f"Continue working on TODO.md tasks."
            ),
        }
        print(json.dumps(output))
        sys.exit(0)

    # All tasks complete or already in a loop - clean up and allow stop
    if incomplete == 0:
        delete_loop_config(session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()
