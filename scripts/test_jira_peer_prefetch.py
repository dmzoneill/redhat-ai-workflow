#!/usr/bin/env python3
"""Test Jira peer data collection for 5 real peers from org roster."""

import json
import os
import subprocess
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.stats.collector import DataCollector


def main():
    roster_path = (
        Path.home()
        / ".config"
        / "aa-workflow"
        / "performance"
        / "org"
        / "org_roster.json"
    )
    if not roster_path.exists():
        print(f"ERROR: Roster not found at {roster_path}")
        return 1

    with open(roster_path) as f:
        roster_data = json.load(f)

    peers = []
    for level, plist in roster_data.get("peers", {}).items():
        for p in plist:
            peers.append(p)
            if len(peers) >= 5:
                break
        if len(peers) >= 5:
            break

    print("=== Step 1: 5 peer usernames from roster ===\n")
    for p in peers:
        print(
            f"  {p['username']} jira={p.get('jira_username','')} gl={p.get('gitlab_username','')} git={p.get('git_author','')}"
        )

    print("\n=== Step 2 & 3: prefetch_jira_quarter for each peer (2026 Q1) ===\n")
    c = DataCollector()
    results = []

    for p in peers:
        jira_user = p.get("jira_username") or p["username"]
        try:
            result = c.prefetch_jira_quarter(jira_user, 2026, 1)
            total = sum(len(v) for v in result.values())
            dates_with_data = [d for d, evts in result.items() if evts]
            sample = None
            if dates_with_data:
                sample_date = dates_with_data[0]
                sample = result[sample_date][0] if result[sample_date] else None

            method = (
                "REST"
                if os.environ.get("JIRA_JPAT") or os.environ.get("JIRA_TOKEN")
                else "rh-issue"
            )
            results.append(
                {
                    "username": jira_user,
                    "total": total,
                    "dates": len(dates_with_data),
                    "method": method,
                    "sample": sample,
                    "error": None,
                }
            )
            print(
                f"User {jira_user}: {total} total events across {len(dates_with_data)} dates (method: {method})"
            )
            if sample:
                print(
                    f"  Sample ({dates_with_data[0]}): {sample.get('title', '')[:80]}..."
                )
        except Exception as e:
            results.append(
                {
                    "username": jira_user,
                    "total": 0,
                    "dates": 0,
                    "method": "error",
                    "sample": None,
                    "error": str(e),
                }
            )
            print(f"User {jira_user}: ERROR - {e}")

    print("\n=== Step 4: JIRA_JPAT check ===")
    jpat = os.environ.get("JIRA_JPAT", "")
    print(
        f"JIRA_JPAT set: {bool(jpat)} (first 10 chars: {jpat[:10] if jpat else 'N/A'})"
    )

    # If any peer returned 0, run rh-issue diagnostic for first failing peer
    zero_peers = [r for r in results if r["total"] == 0 and r["error"] is None]
    if zero_peers:
        first_zero = zero_peers[0]["username"]
        print(f"\n=== Step 4b: rh-issue diagnostic for {first_zero} (no events) ===")
        try:
            rh_result = subprocess.run(
                [
                    "rh-issue",
                    "search",
                    f'resolved >= "2026-01-01" AND resolved < "2026-04-01" AND (assignee = "{first_zero}" OR reporter = "{first_zero}") ORDER BY resolved DESC',
                    "--max-results",
                    "5",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "HOME": str(Path.home())},
            )
            print(f"rh-issue returncode: {rh_result.returncode}")
            print(f"stdout (first 500): {rh_result.stdout[:500]}")
            print(f"stderr (first 500): {rh_result.stderr[:500]}")
        except Exception as e:
            print(f"rh-issue subprocess failed: {e}")

    # REST API direct test if JIRA_JPAT set
    test_user = zero_peers[0]["username"] if zero_peers else peers[0]["username"]
    if jpat:
        print("\n=== Step 5: REST API direct test ===")
        try:
            import urllib.request

            url = f"https://issues.redhat.com/rest/api/2/search?jql=assignee%3D%22{test_user}%22+AND+resolved+%3E%3D+%222026-01-01%22&maxResults=5&fields=key,summary"
            req = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {jpat}"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            print(f"REST API returned {len(data.get('issues', []))} issues")
        except Exception as e:
            print(f"REST API failed: {e}")

    print("\n=== REPORT: Summary Table ===")
    print("username | jira events | dates with data | method")
    print("-" * 55)
    for r in results:
        err_str = f" (error: {r['error'][:40]}...)" if r["error"] else ""
        print(
            f"{r['username']:12} | {r['total']:11} | {r['dates']:15} | {r['method']}{err_str}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
