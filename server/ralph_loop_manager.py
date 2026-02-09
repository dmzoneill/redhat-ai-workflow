"""
Ralph Wiggum Loop Manager

Manages Ralph Wiggum autonomous loops for Cursor sessions.
Each session has its own loop configuration, allowing multiple
concurrent loops without interference.

This module provides:
- Loop registration (start a new loop)
- Loop termination (stop a loop)
- Loop listing (get all active loops)
- Loop status (get status of a specific loop)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

# Configuration directory
LOOPS_DIR = Path.home() / ".config" / "aa-workflow" / "ralph_loops"


def ensure_loops_dir() -> None:
    """Ensure the loops directory exists."""
    LOOPS_DIR.mkdir(parents=True, exist_ok=True)


def _add_todo_stats(config: dict) -> None:
    """Add computed todo stats (task counts, hard stop) to a loop config in-place."""
    todo_path_str = config.get("todo_path")
    if not todo_path_str:
        return
    todo_path = Path(todo_path_str)
    if not todo_path.exists():
        return
    content = todo_path.read_text()
    config["incomplete_tasks"] = content.count("- [ ]")
    config["complete_tasks"] = content.count("- [x]") + content.count("- [X]")
    config["has_hard_stop"] = "**HARD STOP**" in content


def start_ralph_loop(
    session_id: str,
    max_iterations: int = 10,
    todo_path: Optional[str] = None,
    completion_criteria: Optional[list[str]] = None,
    workspace_path: Optional[str] = None,
) -> dict:
    """
    Register a new Ralph Wiggum loop for a Cursor session.

    Args:
        session_id: Unique identifier for the Cursor session
        max_iterations: Maximum number of iterations before stopping
        todo_path: Path to the TODO.md file (defaults to workspace/TODO.md)
        completion_criteria: List of strings that signal completion
        workspace_path: Path to the workspace root

    Returns:
        The created loop configuration
    """
    ensure_loops_dir()

    # Default todo path
    if todo_path is None:
        if workspace_path:
            todo_path = str(Path(workspace_path) / "TODO.md")
        else:
            todo_path = str(Path.cwd() / "TODO.md")

    loop_config = {
        "session_id": session_id,
        "max_iterations": max_iterations,
        "current_iteration": 0,
        "todo_path": todo_path,
        "completion_criteria": completion_criteria or [],
        "started_at": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
        "workspace_path": workspace_path,
        "status": "active",
    }

    config_path = LOOPS_DIR / f"session_{session_id}.json"
    config_path.write_text(json.dumps(loop_config, indent=2))

    return loop_config


def stop_ralph_loop(session_id: str) -> bool:
    """
    Stop a Ralph Wiggum loop (emergency stop).

    Args:
        session_id: The session ID to stop

    Returns:
        True if the loop was stopped, False if it didn't exist
    """
    config_path = LOOPS_DIR / f"session_{session_id}.json"

    if config_path.exists():
        config_path.unlink()
        return True

    return False


def get_loop_status(session_id: str) -> Optional[dict]:
    """
    Get the status of a specific loop.

    Args:
        session_id: The session ID to check

    Returns:
        The loop configuration, or None if not found
    """
    config_path = LOOPS_DIR / f"session_{session_id}.json"

    if not config_path.exists():
        return None

    try:
        config = json.loads(config_path.read_text())
        _add_todo_stats(config)
        return config
    except (json.JSONDecodeError, IOError):
        return None


def list_active_loops() -> list[dict]:
    """
    List all active Ralph Wiggum loops.

    Returns:
        List of loop configurations
    """
    ensure_loops_dir()

    loops = []
    for config_path in LOOPS_DIR.glob("session_*.json"):
        try:
            config = json.loads(config_path.read_text())
            _add_todo_stats(config)
            loops.append(config)
        except (json.JSONDecodeError, IOError):
            continue

    # Sort by started_at descending
    loops.sort(key=lambda x: x.get("started_at", ""), reverse=True)

    return loops


def update_loop_iteration(session_id: str) -> Optional[dict]:
    """
    Increment the iteration counter for a loop.

    Args:
        session_id: The session ID to update

    Returns:
        The updated configuration, or None if not found
    """
    config_path = LOOPS_DIR / f"session_{session_id}.json"

    if not config_path.exists():
        return None

    try:
        config = json.loads(config_path.read_text())
        config["current_iteration"] = config.get("current_iteration", 0) + 1
        config["last_updated"] = datetime.now().isoformat()
        config_path.write_text(json.dumps(config, indent=2))
        return config
    except (json.JSONDecodeError, IOError):
        return None


def add_hard_stop(session_id: str) -> bool:
    """
    Add a HARD STOP marker to the TODO.md for a loop.
    This pauses the loop for manual verification.

    Args:
        session_id: The session ID

    Returns:
        True if successful, False otherwise
    """
    config = get_loop_status(session_id)
    if not config or not config.get("todo_path"):
        return False

    todo_path = Path(config["todo_path"])
    if not todo_path.exists():
        return False

    content = todo_path.read_text()
    if "**HARD STOP**" not in content:
        # Add HARD STOP at the beginning
        content = "**HARD STOP** - Manual verification required\n\n" + content
        todo_path.write_text(content)

    return True


def remove_hard_stop(session_id: str) -> bool:
    """
    Remove the HARD STOP marker from a TODO.md to resume the loop.

    Args:
        session_id: The session ID

    Returns:
        True if successful, False otherwise
    """
    config = get_loop_status(session_id)
    if not config or not config.get("todo_path"):
        return False

    todo_path = Path(config["todo_path"])
    if not todo_path.exists():
        return False

    content = todo_path.read_text()
    if "**HARD STOP**" in content:
        # Remove HARD STOP line
        lines = content.split("\n")
        lines = [line for line in lines if "**HARD STOP**" not in line]
        # Remove leading empty lines
        while lines and not lines[0].strip():
            lines.pop(0)
        todo_path.write_text("\n".join(lines))

    return True


def generate_todo_from_goals(
    goals: str, session_id: str, workspace_path: Optional[str] = None
) -> str:
    """
    Generate a TODO.md file from user goals.

    Args:
        goals: Multi-line string of goals
        session_id: The session ID for the header
        workspace_path: Where to write the TODO.md

    Returns:
        Path to the created TODO.md file
    """
    # Parse goals into task items
    lines = goals.strip().split("\n")
    tasks = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Remove common prefixes
        for prefix in ["- ", "* ", "• ", "→ "]:
            if line.startswith(prefix):
                line = line[len(prefix) :]
                break

        # Remove numbering
        if line and line[0].isdigit():
            parts = line.split(".", 1)
            if len(parts) > 1:
                line = parts[1].strip()

        if line:
            tasks.append(line)

    # Generate TODO.md content
    content = f"""# TODO - Session {session_id}

Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}

## Tasks

{chr(10).join(f"- [ ] {task}" for task in tasks)}

## Notes

- Mark tasks complete with `- [x]` when done
- Add `**HARD STOP**` anywhere to pause for manual verification
- The loop will continue until all tasks are complete or max iterations reached
"""

    # Write to file
    if workspace_path:
        todo_path = Path(workspace_path) / "TODO.md"
    else:
        todo_path = Path.cwd() / "TODO.md"

    todo_path.write_text(content)

    return str(todo_path)


# CLI interface for testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: ralph_loop_manager.py <command> [args]")
        print("Commands: list, start, stop, status, hard-stop, resume")
        sys.exit(1)

    command = sys.argv[1]

    if command == "list":
        loops = list_active_loops()
        print(json.dumps(loops, indent=2))

    elif command == "start" and len(sys.argv) >= 3:
        session_id = sys.argv[2]
        max_iter = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        config = start_ralph_loop(session_id, max_iterations=max_iter)
        print(json.dumps(config, indent=2))

    elif command == "stop" and len(sys.argv) >= 3:
        session_id = sys.argv[2]
        success = stop_ralph_loop(session_id)
        print(f"Stopped: {success}")

    elif command == "status" and len(sys.argv) >= 3:
        session_id = sys.argv[2]
        status = get_loop_status(session_id)
        print(json.dumps(status, indent=2) if status else "Not found")

    elif command == "hard-stop" and len(sys.argv) >= 3:
        session_id = sys.argv[2]
        success = add_hard_stop(session_id)
        print(f"Hard stop added: {success}")

    elif command == "resume" and len(sys.argv) >= 3:
        session_id = sys.argv[2]
        success = remove_hard_stop(session_id)
        print(f"Resumed: {success}")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
