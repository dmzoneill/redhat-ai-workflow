#!/usr/bin/env python3
"""Backfill Q1 2026 performance data for all missing days.

This script collects performance data (git commits, Jira, GitLab) for each
missing weekday in Q1 2026 and saves to the performance directory.

Performance data is stored in: ~/.config/aa-workflow/performance/

Usage:
    python scripts/backfill_q1_2026.py
"""

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configuration
YEAR = 2026
QUARTER = 1
QUARTER_START = date(2026, 1, 1)

# Import centralized paths
from server.paths import PERFORMANCE_DIR, get_performance_quarter_dir  # noqa: E402

PERF_BASE_DIR = PERFORMANCE_DIR
PERF_DIR = get_performance_quarter_dir(YEAR, QUARTER)
DAILY_DIR = PERF_DIR / "daily"

# Repos to scan for commits
REPOS = [
    Path.home() / "src" / "automation-analytics-backend",
    Path.home() / "src" / "app-interface",
    Path.home() / "src" / "redhat-ai-workflow",
    Path.home() / "src" / "pdf-generator",
]

# Git author to match (partial match works with git --author)
GIT_AUTHOR = "David O Neill"


def get_missing_dates() -> list[date]:
    """Find all weekdays in Q1 2026 without performance data."""
    today = date.today()

    # Get existing daily files
    existing = set()
    if DAILY_DIR.exists():
        existing = {f.stem for f in DAILY_DIR.glob("*.json")}

    print(f"Found {len(existing)} existing daily files")

    # Find missing weekdays
    missing = []
    current = QUARTER_START
    while current <= today:
        if current.weekday() < 5:  # Mon-Fri only
            if current.isoformat() not in existing:
                missing.append(current)
        current += timedelta(days=1)

    return missing


def get_commits_for_date(target: date) -> list[dict]:
    """Get git commits from all repos for a specific date."""
    commits = []
    date_str = target.isoformat()

    for repo in REPOS:
        if not repo.exists():
            continue

        try:
            cmd = [
                "git",
                "-C",
                str(repo),
                "log",
                f"--since={date_str} 00:00:00",
                f"--until={date_str} 23:59:59",
                f"--author={GIT_AUTHOR}",
                "--format=%H|%s|%ad",
                "--date=iso",
                "--all",
            ]
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)

            for line in output.strip().split("\n"):
                if line:
                    parts = line.split("|", 2)
                    if len(parts) >= 2:
                        commits.append(
                            {
                                "repo": repo.name,
                                "sha": parts[0][:8],
                                "full_sha": parts[0],
                                "message": parts[1],
                                "date": parts[2] if len(parts) > 2 else date_str,
                            }
                        )
        except Exception:
            pass

    return commits


def map_competencies(title: str, source: str, event_type: str) -> dict[str, int]:
    """Map an event to competency points based on keywords."""
    points = {}
    title_lower = title.lower()

    # Technical Contribution - base for most work
    if event_type in ["mr_merged", "issue_resolved", "commit"]:
        points["technical_contribution"] = 2

    # Planning & Execution
    if any(k in title_lower for k in ["planning", "roadmap", "spike", "design"]):
        points["planning_execution"] = 2

    # Collaboration
    if any(k in title_lower for k in ["review", "pair", "feedback", "merge"]):
        points["collaboration"] = 2

    # Mentorship
    if any(
        k in title_lower for k in ["mentor", "onboard", "training", "newcomer", "doc"]
    ):
        points["mentorship"] = 3

    # Continuous Improvement
    if any(
        k in title_lower
        for k in [
            "ci/cd",
            "pipeline",
            "automation",
            "tooling",
            "refactor",
            "fix",
            "improve",
        ]
    ):
        points["continuous_improvement"] = 3

    # Creativity & Innovation
    if any(
        k in title_lower
        for k in [
            "poc",
            "prototype",
            "innovation",
            "experiment",
            "ai",
            "new",
            "feature",
        ]
    ):
        points["creativity_innovation"] = 4

    # Leadership
    if any(k in title_lower for k in ["cross-team", "lead", "architecture", "design"]):
        points["leadership"] = 3

    # Portfolio Impact
    if any(k in title_lower for k in ["api", "schema", "interface", "app-interface"]):
        points["portfolio_impact"] = 4

    # End-to-End Delivery
    if any(
        k in title_lower
        for k in ["release", "deploy", "customer", "production", "prod"]
    ):
        points["end_to_end_delivery"] = 3

    # Opportunity Recognition (upstream)
    if source == "github":
        points["opportunity_recognition"] = 4

    # Technical Knowledge (docs)
    if any(k in title_lower for k in ["doc", "readme", "documentation"]):
        points["technical_knowledge"] = 3

    return points


def collect_day(target: date) -> dict:
    """Collect all performance data for a specific date."""
    events = []
    seen_ids = set()
    date_str = target.isoformat()
    day_of_quarter = (target - QUARTER_START).days + 1

    # Get git commits
    commits = get_commits_for_date(target)

    for commit in commits:
        event_id = f"git:{commit['repo']}:{commit['sha']}"
        if event_id not in seen_ids:
            seen_ids.add(event_id)
            points = map_competencies(commit["message"], "git", "commit")
            events.append(
                {
                    "id": event_id,
                    "source": "git",
                    "type": "commit",
                    "item_id": commit["sha"],
                    "title": f"[{commit['repo']}] {commit['message']}",
                    "timestamp": commit.get("date", date_str),
                    "points": points,
                }
            )

    # Calculate daily points by competency (with daily cap of 15)
    daily_points = {}
    daily_cap = 15

    for event in events:
        for comp_id, pts in event.get("points", {}).items():
            current = daily_points.get(comp_id, 0)
            daily_points[comp_id] = min(current + pts, daily_cap)

    daily_total = sum(daily_points.values())

    # Build daily data
    daily_data = {
        "date": date_str,
        "day_of_quarter": day_of_quarter,
        "events": events,
        "daily_points": daily_points,
        "daily_total": daily_total,
        "saved_at": date.today().isoformat(),
    }

    # Add note if no activity
    if not events:
        daily_data["notes"] = f"No activity captured - no commits found on {date_str}"

    return daily_data


def save_daily_data(data: dict) -> Path:
    """Save daily data to JSON file."""
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    file_path = DAILY_DIR / f"{data['date']}.json"

    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

    return file_path


def update_summary():
    """Aggregate all daily data into a quarter summary."""
    cumulative = {}
    highlights = []
    total_events = 0

    for daily_file in sorted(DAILY_DIR.glob("*.json")):
        with open(daily_file) as f:
            data = json.load(f)

        for comp_id, pts in data.get("daily_points", {}).items():
            cumulative[comp_id] = cumulative.get(comp_id, 0) + pts

        total_events += len(data.get("events", []))

        # Collect highlights from events
        for event in data.get("events", [])[:2]:
            highlights.append(event.get("title", "")[:80])

    # Calculate percentages (max 100 pts per competency per quarter)
    max_per_quarter = 100
    percentages = {
        k: min(100, round(v / max_per_quarter * 100)) for k, v in cumulative.items()
    }
    overall = (
        round(sum(percentages.values()) / max(len(percentages), 1))
        if percentages
        else 0
    )

    # Find gaps (below 50%)
    gaps = [k for k, v in percentages.items() if v < 50]

    # Calculate day of quarter
    day_of_quarter = (date.today() - QUARTER_START).days + 1

    summary = {
        "year": YEAR,
        "quarter": QUARTER,
        "day_of_quarter": day_of_quarter,
        "cumulative_points": cumulative,
        "cumulative_percentage": percentages,
        "overall_percentage": overall,
        "total_events": total_events,
        "highlights": highlights[:10],
        "gaps": gaps,
    }

    summary_file = PERF_DIR / "summary.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nSummary saved: {summary_file}")
    print(f"Overall: {overall}%")
    print(f"Total events: {total_events}")

    return summary


def update_workspace_state(summary: dict):
    """Update workspace state for VS Code UI."""
    from server.paths import WORKSPACE_STATES_FILE

    state_file = WORKSPACE_STATES_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)

    state = {}
    if state_file.exists():
        try:
            with open(state_file) as f:
                state = json.load(f)
        except Exception:
            pass

    cumulative = summary.get("cumulative_points", {})
    percentages = summary.get("cumulative_percentage", {})

    state["performance"] = {
        "last_updated": date.today().isoformat(),
        "quarter": f"Q{QUARTER} {YEAR}",
        "day_of_quarter": summary.get("day_of_quarter", 24),
        "overall_percentage": summary.get("overall_percentage", 0),
        "competencies": {
            comp_id: {
                "points": cumulative.get(comp_id, 0),
                "percentage": percentages.get(comp_id, 0),
            }
            for comp_id in cumulative
        },
        "highlights": summary.get("highlights", [])[:5],
        "gaps": summary.get("gaps", []),
    }

    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)

    print(f"Workspace state updated: {state_file}")


def main():
    """Main entry point."""
    print("=" * 60)
    print("Q1 2026 Performance Data Backfill")
    print("=" * 60)

    # Ensure directories exist
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    missing = get_missing_dates()

    if not missing:
        print("\n✅ No missing days to backfill!")
        # Still update summary in case it's stale
        summary = update_summary()
        update_workspace_state(summary)
        return 0

    print(f"\nFound {len(missing)} missing weekdays to backfill:")
    for d in missing:
        print(f"  - {d.isoformat()} ({d.strftime('%A')})")

    print("\nScanning repos:")
    for repo in REPOS:
        status = "✓" if repo.exists() else "✗"
        print(f"  {status} {repo}")

    print("\nStarting backfill...")

    success = 0
    failed = 0
    total_events = 0

    for target in missing:
        print(f"\n{'─'*40}")
        print(f"Processing: {target.isoformat()} ({target.strftime('%A')})")

        try:
            data = collect_day(target)
            save_daily_data(data)

            event_count = len(data.get("events", []))
            total_events += event_count
            daily_total = data.get("daily_total", 0)

            if event_count > 0:
                print(f"  ✅ {event_count} events, {daily_total} points")
            else:
                print("  ⚪ No activity found")

            success += 1

        except Exception as e:
            print(f"  ❌ Error: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print("BACKFILL COMPLETE")
    print("=" * 60)
    print(f"✅ Days processed: {success}")
    print(f"❌ Days failed:    {failed}")
    print(f"📊 Total events:   {total_events}")

    # Update summary and workspace state
    print("\nUpdating quarter summary...")
    summary = update_summary()
    update_workspace_state(summary)

    print("\n✨ Done! Refresh the Performance tab in VS Code to see the data.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
