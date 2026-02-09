#!/usr/bin/env python3
"""One-time migration script to extract state from config.json to state.json.

This script:
1. Reads enabled flags from config.json (schedules, sprint, google_calendar, gmail)
2. Creates state.json with extracted state
3. Does NOT modify config.json (run cleanup separately)

Usage:
    python scripts/migrate_state.py

    # Dry run (show what would be extracted):
    python scripts/migrate_state.py --dry-run
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.json"
STATE_FILE = PROJECT_ROOT / "state.json"


def load_config() -> dict:
    """Load config.json."""
    if not CONFIG_FILE.exists():
        print(f"ERROR: {CONFIG_FILE} not found")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        return json.load(f)


def extract_state(config: dict) -> dict:
    """Extract state from config.json."""
    state = {
        "version": 1,
        "services": {},
        "jobs": {},
        "last_updated": datetime.now().isoformat(),
    }

    # Extract service enabled states
    schedules = config.get("schedules", {})
    state["services"]["scheduler"] = {"enabled": schedules.get("enabled", False)}

    sprint = config.get("sprint", {})
    state["services"]["sprint_bot"] = {"enabled": sprint.get("enabled", False)}

    google_calendar = config.get("google_calendar", {})
    state["services"]["google_calendar"] = {
        "enabled": google_calendar.get("enabled", False)
    }

    gmail = config.get("gmail", {})
    state["services"]["gmail"] = {"enabled": gmail.get("enabled", False)}

    # Extract job enabled states
    jobs = schedules.get("jobs", [])
    for job in jobs:
        job_name = job.get("name")
        if job_name:
            state["jobs"][job_name] = {"enabled": job.get("enabled", True)}

    return state


def main():
    parser = argparse.ArgumentParser(
        description="Migrate state from config.json to state.json"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be extracted without writing",
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing state.json"
    )
    args = parser.parse_args()

    # Check if state.json already exists
    if STATE_FILE.exists() and not args.force and not args.dry_run:
        print(f"ERROR: {STATE_FILE} already exists. Use --force to overwrite.")
        sys.exit(1)

    # Load config and extract state
    config = load_config()
    state = extract_state(config)

    # Display extracted state
    print("Extracted state from config.json:")
    print("-" * 40)
    print(json.dumps(state, indent=2))
    print("-" * 40)

    if args.dry_run:
        print("\nDry run - no changes made.")
        return

    # Write state.json
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")

    print(f"\n✅ State written to {STATE_FILE}")
    print("\nNext steps:")
    print("1. Verify state.json looks correct")
    print("2. Remove 'enabled' flags from config.json (see cleanup script)")
    print("3. Test that services still work correctly")


if __name__ == "__main__":
    main()
