#!/usr/bin/env python3
"""Fix session projects - Backfill correct project for existing sessions.

This script scans all sessions and corrects the project field based on:
1. Chat content analysis (repo names, file paths, GitLab paths)
2. Issue key lookup (query Jira for component)
3. Session name analysis

Usage:
    python scripts/fix_session_projects.py              # Dry run (show changes)
    python scripts/fix_session_projects.py --apply      # Apply changes
    python scripts/fix_session_projects.py --verbose    # Show detailed analysis
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from server.paths import WORKSPACE_STATES_FILE  # noqa: E402


def load_config() -> dict:
    """Load config.json."""
    config_file = PROJECT_ROOT / "config.json"
    if config_file.exists():
        return json.loads(config_file.read_text())
    return {}


def get_valid_projects() -> set[str]:
    """Get set of valid project names from config."""
    config = load_config()
    return set(config.get("repositories", {}).keys())


def detect_project_from_name(name: str, valid_projects: set[str]) -> str | None:
    """Detect project from session name."""
    if not name:
        return None

    name_lower = name.lower()

    # Direct project name match
    for proj in valid_projects:
        if proj.lower() in name_lower:
            return proj

    # Keywords that suggest automation-analytics-backend
    backend_keywords = [
        "billing",
        "api",
        "fastapi",
        "ingestion",
        "reports",
        "backend",
        "analytics",
        "tower-analytics",
    ]
    for kw in backend_keywords:
        if kw in name_lower:
            return "automation-analytics-backend"

    # Keywords for pdf-generator
    if "pdf" in name_lower or "generator" in name_lower:
        return "pdf-generator"

    # Keywords for app-interface
    if "app-interface" in name_lower or "saas" in name_lower:
        return "app-interface"

    return None


def detect_project_from_issue_key(issue_key: str, config: dict) -> str | None:
    """Detect project from issue key by querying Jira component."""
    if not issue_key:
        return None

    # Parse first issue key if multiple
    first_key = issue_key.split(",")[0].strip()

    # Try to get component from Jira
    try:
        result = subprocess.run(
            ["rh-issue", "view", first_key, "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            issue_data = json.loads(result.stdout)
            components = issue_data.get("fields", {}).get("components", [])

            # Match component to repo
            repos = config.get("repositories", {})
            for comp in components:
                comp_name = comp.get("name", "")
                for repo_name, repo_config in repos.items():
                    if repo_config.get("jira_component") == comp_name:
                        return repo_name

    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        pass

    return None


def scan_cursor_chat_for_project(chat_id: str, valid_projects: set[str]) -> str | None:
    """Scan Cursor chat content for project indicators."""
    try:
        global_db = (
            Path.home()
            / ".config"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )
        if not global_db.exists():
            return None

        # Query chat content
        query = f"SELECT value FROM cursorDiskKV WHERE key LIKE 'bubbleId:{chat_id}:%'"
        result = subprocess.run(
            ["sqlite3", str(global_db), query],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return None

        # Build patterns for each project
        project_scores: dict[str, int] = {}

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            try:
                data = json.loads(line)
                text = data.get("text", "")
                if not text:
                    continue

                for proj in valid_projects:
                    # Skip redhat-ai-workflow as it's the workspace default
                    if proj == "redhat-ai-workflow":
                        continue

                    # Check various patterns
                    patterns = [
                        # session_start(project="proj") - high value
                        (rf'project\s*=\s*["\']({re.escape(proj)})["\']', 10),
                        # File paths
                        (
                            rf"/(?:home|Users)/[^/]+/(?:src|projects?)/({re.escape(proj)})/",
                            5,
                        ),
                        # GitLab paths
                        (rf'[\w-]+/({re.escape(proj)})(?:\s|$|["\'\]])', 4),
                        # Direct mention
                        (rf"\b({re.escape(proj)})\b", 2),
                    ]

                    for pattern, score in patterns:
                        if re.search(pattern, text, re.IGNORECASE):
                            project_scores[proj] = project_scores.get(proj, 0) + score

            except json.JSONDecodeError:
                continue

        # Return highest scoring project
        if project_scores:
            best = max(project_scores.items(), key=lambda x: x[1])
            if best[1] >= 5:  # Minimum confidence threshold
                return best[0]

    except Exception:
        pass

    return None


def fix_session_projects(apply: bool = False, verbose: bool = False) -> int:
    """Fix session projects in workspace_states.json.

    Args:
        apply: If True, apply changes. If False, dry run.
        verbose: Show detailed analysis.

    Returns:
        Number of sessions that need/were fixed.
    """
    if not WORKSPACE_STATES_FILE.exists():
        print(f"Error: {WORKSPACE_STATES_FILE} not found")
        return 0

    # Load workspace states
    data = json.loads(WORKSPACE_STATES_FILE.read_text())
    config = load_config()
    valid_projects = get_valid_projects()

    print(f"Scanning sessions in {WORKSPACE_STATES_FILE}")
    print(f"Valid projects: {', '.join(sorted(valid_projects))}")
    print()

    fixes_needed = 0
    fixes_applied = 0

    workspaces = data.get("workspaces", {})
    for _workspace_uri, workspace_data in workspaces.items():
        sessions = workspace_data.get("sessions", {})

        for session_id, session in sessions.items():
            current_project = session.get("project")
            is_auto = session.get("is_project_auto_detected", False)
            name = session.get("name", "")
            issue_key = session.get("issue_key", "")

            # Skip if project was explicitly set (not auto-detected)
            if not is_auto and current_project != "redhat-ai-workflow":
                if verbose:
                    print(
                        f"  [{session_id[:8]}] {name[:40]:<40} - SKIP (explicit: {current_project})"
                    )
                continue

            # Try to detect correct project
            detected = None
            detection_source = None

            # 1. Try chat content analysis
            detected = scan_cursor_chat_for_project(session_id, valid_projects)
            if detected:
                detection_source = "chat_content"

            # 2. Try session name
            if not detected:
                detected = detect_project_from_name(name, valid_projects)
                if detected:
                    detection_source = "name"

            # 3. Try issue key lookup
            if not detected and issue_key:
                detected = detect_project_from_issue_key(issue_key, config)
                if detected:
                    detection_source = "jira"

            # Check if fix needed
            if detected and detected != current_project:
                fixes_needed += 1

                action = "WOULD FIX" if not apply else "FIXED"
                print(f"  [{session_id[:8]}] {name[:40]:<40} - {action}")
                print(f"    {current_project} -> {detected} ({detection_source})")

                if apply:
                    session["project"] = detected
                    session["is_project_auto_detected"] = False
                    fixes_applied += 1
            elif verbose:
                print(f"  [{session_id[:8]}] {name[:40]:<40} - OK ({current_project})")

    print()
    print(f"Sessions needing fix: {fixes_needed}")

    if apply and fixes_applied > 0:
        # Save changes
        data["saved_at"] = datetime.now().isoformat()
        WORKSPACE_STATES_FILE.write_text(json.dumps(data, indent=2))
        print(f"Applied {fixes_applied} fixes to {WORKSPACE_STATES_FILE}")
    elif not apply and fixes_needed > 0:
        print("Run with --apply to apply changes")

    return fixes_needed


def main():
    parser = argparse.ArgumentParser(
        description="Fix session projects in workspace_states.json"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Apply changes (default is dry run)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed analysis"
    )

    args = parser.parse_args()

    fixes = fix_session_projects(apply=args.apply, verbose=args.verbose)

    return 0 if fixes == 0 or args.apply else 1


if __name__ == "__main__":
    sys.exit(main())
