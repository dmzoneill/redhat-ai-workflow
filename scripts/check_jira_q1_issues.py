#!/usr/bin/env python3
"""Check Jira AAP issues for current user in Q1 2026."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.utils import run_cmd_sync  # noqa: E402

# 1. Search for ALL AAP issues assigned to current user updated in Q1 2026
print("=== All AAP issues assigned to user, updated Q1 2026 ===")
ok, out = run_cmd_sync(
    [
        "rh-issue",
        "search",
        (
            "project = AAP AND assignee = currentUser() AND "
            'updated >= "2026-01-01" AND updated <= "2026-03-31" '
            "ORDER BY updated DESC"
        ),
        "--max-results",
        "100",
    ],
    timeout=60,
)
if ok:
    lines = [line for line in out.strip().split("\n") if "AAP-" in line]
    print(f"Total issues found: {len(lines)}")
    for line in lines:
        print(line[:140])
else:
    print(f"FAILED: {out[:300]}")

print()

# 2. Also check issues where user is reporter
print("=== AAP issues where user is reporter, updated Q1 2026 ===")
ok2, out2 = run_cmd_sync(
    [
        "rh-issue",
        "search",
        (
            "project = AAP AND reporter = currentUser() AND "
            'updated >= "2026-01-01" AND updated <= "2026-03-31" AND '
            "assignee != currentUser() ORDER BY updated DESC"
        ),
        "--max-results",
        "50",
    ],
    timeout=60,
)
if ok2:
    lines2 = [line for line in out2.strip().split("\n") if "AAP-" in line]
    print(f"Total issues found: {len(lines2)}")
    for line in lines2:
        print(line[:140])
else:
    print(f"FAILED: {out2[:300]}")

print()

# 3. Check issues where user has done work (is in participants/watchers) - broader net
print("=== AAP issues where user is watcher, updated Q1 2026 ===")
ok3, out3 = run_cmd_sync(
    [
        "rh-issue",
        "search",
        (
            "project = AAP AND watcher = currentUser() AND "
            'updated >= "2026-01-01" AND updated <= "2026-03-31" AND '
            "assignee != currentUser() AND reporter != currentUser() "
            "ORDER BY updated DESC"
        ),
        "--max-results",
        "50",
    ],
    timeout=60,
)
if ok3:
    lines3 = [line for line in out3.strip().split("\n") if "AAP-" in line]
    print(f"Total issues found: {len(lines3)}")
    for line in lines3:
        print(line[:140])
else:
    print(f"FAILED: {out3[:300]}")
