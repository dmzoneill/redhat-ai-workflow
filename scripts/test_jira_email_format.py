#!/usr/bin/env python3
"""Verify Red Hat Jira uses email format for assignee/reporter."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from services.stats.collector import _jira_rest_search

peers = [
    ("arestlel", "arestlel@redhat.com"),
    ("aoladele", "aoladele@redhat.com"),
    ("jheadley", "jheadley@redhat.com"),
    ("apotozni", "apotozni@redhat.com"),
    ("siddasha", "siddasha@redhat.com"),
]

print("Testing with email format (user@redhat.com) for 2025 Q1:")
for kerb, email in peers:
    jql = (
        f"(assignee = '{email}' OR reporter = '{email}') "
        f"AND resolved >= '2025-01-01' AND resolved < '2025-04-01'"
    )
    issues = _jira_rest_search(jql, fields="key,summary,resolutiondate", max_results=50)
    count = len(issues) if issues else 0
    print(f"  {kerb}: {count} issues (via {email})")
