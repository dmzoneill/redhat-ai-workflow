#!/usr/bin/env python3
"""Test shared drive peer data capture end-to-end."""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.stats.gdrive_collector import (
    _get_shared_drive_ids,
    collect_shared_drive_peer_contributions,
    ensure_shared_drive_index,
    load_shared_drive_user_index,
)
from services.stats.scorer import get_effective_defs, map_competencies_with_signals


def main():
    target = date.today()
    year = target.year
    quarter = (target.month - 1) // 3 + 1

    perf_dir = Path.home() / f".config/aa-workflow/performance/{year}/q{quarter}"
    perf_dir.mkdir(parents=True, exist_ok=True)

    print("=== Step 1: Check config ===")
    drive_ids = _get_shared_drive_ids()
    print(f"  Shared drives from config: {drive_ids}")
    if not drive_ids:
        print("  ERROR: No shared drives configured")
        sys.exit(1)

    print("\n=== Step 2: Load or build shared drive index ===")
    user_index = load_shared_drive_user_index(perf_dir)
    if user_index:
        print(f"  Using cached index: {len(user_index)} users")
    else:
        print("  Building fresh index (this takes ~3 min)...")
        user_index = ensure_shared_drive_index(
            perf_dir=perf_dir,
            drive_ids=drive_ids,
            target=target,
            force_refresh=True,
            max_revision_files=100,
        )
        print(f"  Indexed {len(user_index)} unique users")

    if not user_index:
        print("  ERROR: No users found in index")
        sys.exit(1)

    top_contributors = sorted(
        user_index.items(),
        key=lambda x: sum(c["revision_count"] for c in x[1]),
        reverse=True,
    )[:10]
    print(f"\n  Top 10 contributors by revision count:")
    for email, contributions in top_contributors:
        total_revs = sum(c["revision_count"] for c in contributions)
        files = len(contributions)
        print(f"    {email:<40} {files} files, {total_revs} revisions")

    roster_path = Path.home() / ".config/aa-workflow/performance/org/org_roster.json"
    test_peers = []
    if roster_path.exists():
        with open(roster_path) as f:
            roster = json.load(f)
        for level, plist in roster.get("peers", {}).items():
            for p in plist:
                email = f"{p['username']}@redhat.com"
                if email in user_index:
                    test_peers.append((p["username"], email, level))
                    if len(test_peers) >= 3:
                        break
            if len(test_peers) >= 3:
                break

    if not test_peers:
        email = top_contributors[0][0]
        test_peers = [(email.split("@")[0], email, "unknown")]

    comp_defs = get_effective_defs()

    for peer_name, peer_email, peer_level in test_peers:
        print(f"\n=== Peer: {peer_name} ({peer_level}) ===")
        events = collect_shared_drive_peer_contributions(
            perf_dir=perf_dir,
            peer_email=peer_email,
            target=target,
        )
        print(f"  Events generated: {len(events)}")

        for ev in events[:3]:
            print(f"\n  {ev['title'][:65]}")
            print(
                f"    Type: {ev['type']}, Role: {ev['gdrive_role']}, "
                f"Revisions: {ev['gdrive_revision_count']}"
            )
            print(f"    Classification: {ev['gdrive_classification']}")

            points, signals = map_competencies_with_signals(
                classification_text=ev.get("extra_classification_text", ""),
                source=ev.get("source", "gdrive"),
                event_type=ev.get("type", ""),
                scope="story",
                role="contributor",
                effective_defs=comp_defs,
            )
            if points:
                for comp_id, pts in sorted(points.items(), key=lambda x: -x[1]):
                    sig = signals.get(comp_id, 0)
                    print(f"    -> {comp_id}: {pts}pts ({sig} signals)")
            else:
                top_sigs = sorted(signals.items(), key=lambda x: -x[1])[:3]
                if top_sigs:
                    print(
                        f"    -> Below threshold. Top signals: "
                        f"{', '.join(f'{k}={v}' for k, v in top_sigs)}"
                    )
                else:
                    print(f"    -> No signals matched")

    print(f"\n=== Cache Status ===")
    index_file = perf_dir / "gdrive_shared_drive_user_index.json"
    cache_file = perf_dir / "gdrive_shared_drive_cache.json"
    print(
        f"  Index file: {index_file.exists()} ({index_file.stat().st_size // 1024}KB)"
        if index_file.exists()
        else "  Index: not found"
    )
    print(
        f"  Cache file: {cache_file.exists()} ({cache_file.stat().st_size // 1024}KB)"
        if cache_file.exists()
        else "  Cache: not found"
    )

    print(f"\n=== Peer Roster Coverage ===")
    if roster_path.exists():
        all_peer_emails = set()
        for level, plist in roster.get("peers", {}).items():
            for p in plist:
                all_peer_emails.add(f"{p['username']}@redhat.com")
        covered = all_peer_emails & set(user_index.keys())
        print(f"  Total peers: {len(all_peer_emails)}")
        print(
            f"  Peers with shared drive activity: {len(covered)} ({100*len(covered)//len(all_peer_emails)}%)"
        )
        for email in sorted(covered):
            contribs = user_index[email]
            total_revs = sum(c["revision_count"] for c in contribs)
            print(f"    {email:<40} {len(contribs)} files, {total_revs} revisions")


if __name__ == "__main__":
    main()
