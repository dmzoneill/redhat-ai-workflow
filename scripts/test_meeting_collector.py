#!/usr/bin/env python3
"""Test meeting collector end-to-end with scoring."""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.stats.meeting_collector import (
    collect_meeting_contributions,
    collect_meeting_peer_contributions,
    ensure_meeting_peer_index,
)
from services.stats.scorer import get_effective_defs, map_competencies_with_signals


def main():
    target = date.today()
    year = target.year
    quarter = (target.month - 1) // 3 + 1

    perf_dir = Path.home() / f".config/aa-workflow/performance/{year}/q{quarter}"
    perf_dir.mkdir(parents=True, exist_ok=True)

    print("=== Step 1: Self-collection (Calendar + Meet) ===")
    events = collect_meeting_contributions(
        perf_dir=perf_dir,
        target=target,
        force_refresh=True,
        include_meet=True,
    )
    print(f"  Total events: {len(events)}")

    by_type = {}
    organized = 0
    attended = 0
    for ev in events:
        cls = ev.get("meeting_classification", "?")
        by_type[cls] = by_type.get(cls, 0) + 1
        if ev.get("meeting_is_organizer"):
            organized += 1
        else:
            attended += 1

    print(f"  Organized: {organized}, Attended: {attended}")
    print(f"  By classification:")
    for cls, count in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"    {cls}: {count}")

    with_meet = sum(1 for e in events if e.get("meeting_has_meet_data"))
    print(f"  With actual Meet data: {with_meet}")

    print(f"\n=== Step 2: Scoring test ===")
    comp_defs = get_effective_defs()
    scored_count = 0
    comp_hits = {}

    for ev in events:
        points, signals = map_competencies_with_signals(
            classification_text=ev.get("extra_classification_text", ""),
            source=ev.get("source", "meeting"),
            event_type=ev.get("type", ""),
            scope="story",
            role=ev.get("meeting_role", "contributor"),
            effective_defs=comp_defs,
        )
        if points:
            scored_count += 1
            for comp_id in points:
                comp_hits[comp_id] = comp_hits.get(comp_id, 0) + 1

    print(f"  Events scoring points: {scored_count}/{len(events)}")
    print(f"  Competency hits:")
    for comp_id, count in sorted(comp_hits.items(), key=lambda x: -x[1]):
        print(f"    {comp_id}: {count} events")

    print(f"\n  Sample scored events:")
    for ev in events[:5]:
        points, signals = map_competencies_with_signals(
            classification_text=ev.get("extra_classification_text", ""),
            source=ev.get("source", "meeting"),
            event_type=ev.get("type", ""),
            scope="story",
            role=ev.get("meeting_role", "contributor"),
            effective_defs=comp_defs,
        )
        print(f"\n  {ev['title'][:60]}")
        print(f"    Type: {ev['type']}")
        print(f"    Classification: {ev.get('meeting_classification')}")
        if points:
            for comp_id, pts in sorted(points.items(), key=lambda x: -x[1]):
                print(f"    -> {comp_id}: {pts}pts ({signals.get(comp_id, 0)} signals)")
        else:
            top = sorted(signals.items(), key=lambda x: -x[1])[:3]
            print(
                f"    -> No points. Top signals: {', '.join(f'{k}={v}' for k, v in top)}"
            )

    print(f"\n=== Step 3: Peer index ===")
    peer_index = ensure_meeting_peer_index(perf_dir, target, force_refresh=True)
    print(f"  Unique attendees indexed: {len(peer_index)}")

    top_attendees = sorted(
        peer_index.items(),
        key=lambda x: len(x[1]),
        reverse=True,
    )[:10]
    print(f"  Top 10 co-attendees:")
    for email, meetings in top_attendees:
        print(f"    {email:<45} {len(meetings)} meetings")

    roster_path = Path.home() / ".config/aa-workflow/performance/org/org_roster.json"
    if roster_path.exists():
        with open(roster_path) as f:
            roster = json.load(f)
        peer_emails = set()
        for level, plist in roster.get("peers", {}).items():
            for p in plist:
                peer_emails.add(f"{p['username']}@redhat.com")

        covered = peer_emails & set(peer_index.keys())
        print(f"\n  Peers in roster: {len(peer_emails)}")
        print(
            f"  Peers with meeting data: {len(covered)} ({100*len(covered)//max(len(peer_emails),1)}%)"
        )

        test_peer = None
        for email in sorted(covered, key=lambda e: -len(peer_index.get(e, []))):
            test_peer = email
            break

        if test_peer:
            print(f"\n=== Step 4: Peer event generation ({test_peer}) ===")
            peer_events = collect_meeting_peer_contributions(
                perf_dir=perf_dir,
                peer_email=test_peer,
                target=target,
            )
            print(f"  Events: {len(peer_events)}")
            for ev in peer_events[:3]:
                points, signals = map_competencies_with_signals(
                    classification_text=ev.get("extra_classification_text", ""),
                    source=ev.get("source", "meeting"),
                    event_type=ev.get("type", ""),
                    scope="story",
                    role=ev.get("meeting_role", "contributor"),
                    effective_defs=comp_defs,
                )
                print(f"\n  {ev['title'][:60]}")
                print(f"    Type: {ev['type']}")
                if points:
                    for comp_id, pts in sorted(points.items(), key=lambda x: -x[1]):
                        print(f"    -> {comp_id}: {pts}pts")

    print(f"\n=== Cache status ===")
    for fname in ["meeting_contributions_cache.json", "meeting_peer_index_cache.json"]:
        p = perf_dir / fname
        if p.exists():
            print(f"  {fname}: {p.stat().st_size // 1024}KB")
        else:
            print(f"  {fname}: not found")


if __name__ == "__main__":
    main()
