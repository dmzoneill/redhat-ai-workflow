#!/usr/bin/env python3
"""
Audit peer data backfill for Q1 2026 (Jan 1 - Feb 22).
Checks: daily file count, empty files, date gaps, suspicious patterns,
summary vs daily mismatch, level distribution.
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

PEERS_DIR = Path.home() / ".config/aa-workflow/performance/2026/q1/performance/peers"
EXPECTED_WEEKDAYS = 39  # Jan 1 - Feb 22, 2026
SUSPICIOUS_THRESHOLD = 35  # Peers with fewer than this are suspicious
MIN_MEANINGFUL_EVENTS = 10


def is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5  # Mon=0 .. Fri=4


def get_expected_weekdays():
    """Jan 1 - Feb 22, 2026 weekdays."""
    start = datetime(2026, 1, 1)
    end = datetime(2026, 2, 22)
    days = []
    d = start
    while d <= end:
        if is_weekday(d):
            days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return days


def load_peer_data(peer_dir: Path):
    """Load daily files and summary for a peer. Returns (daily_data, summary, malformed, empty_events)."""
    daily_dir = peer_dir / "daily"
    if not daily_dir.exists():
        return [], None, [], []

    daily_files = list(daily_dir.glob("*.json"))
    daily_data = []
    malformed = []
    empty_events = []

    for f in daily_files:
        try:
            with open(f) as fp:
                data = json.load(fp)
        except (json.JSONDecodeError, OSError) as e:
            malformed.append((f.name, str(e)))
            continue

        events = data.get("events", [])
        if not isinstance(events, list):
            malformed.append((f.name, "events is not a list"))
        elif len(events) == 0:
            empty_events.append(f.stem)
        else:
            daily_data.append((f.stem, len(events), data))

    summary_path = peer_dir / "summary.json"
    summary = None
    if summary_path.exists():
        try:
            with open(summary_path) as fp:
                summary = json.load(fp)
        except (json.JSONDecodeError, OSError):
            pass

    return daily_data, summary, malformed, empty_events


def find_date_gaps(dates: list[str], expected: list[str]) -> list[str]:
    """Find missing weekdays in dates. Returns list of missing dates."""
    date_set = set(dates)
    return [d for d in expected if d not in date_set]


def get_sources_from_daily(daily_data) -> set:
    """Extract unique event sources from daily data."""
    sources = set()
    for _, _, data in daily_data:
        for ev in data.get("events", []):
            if isinstance(ev, dict) and "source" in ev:
                sources.add(ev["source"])
    return sources


def main():
    expected_weekdays = get_expected_weekdays()
    print(
        f"Expected weekdays: {len(expected_weekdays)} ({expected_weekdays[0]} to {expected_weekdays[-1]})"
    )

    peer_dirs = [
        d for d in PEERS_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")
    ]
    if (PEERS_DIR / "benchmarks.json").exists():
        # benchmarks.json might be in peers dir - skip
        pass
    peer_dirs = [
        d for d in peer_dirs if (d / "daily").exists() or (d / "summary.json").exists()
    ]
    if not peer_dirs:
        peer_dirs = [d for d in PEERS_DIR.iterdir() if d.is_dir()]

    print(f"Peers found: {len(peer_dirs)}\n")

    # 1. Daily file count per peer
    low_file_count = []
    # 2. Empty files
    peers_with_empty = []
    peers_all_empty = []
    # 3. Date gaps
    peers_with_gaps = []
    # 4. Suspicious patterns
    peers_zero_events = []
    peers_sudden_stop = []
    # 5. Summary vs daily
    summary_mismatches = []
    # 6. Level distribution
    level_stats = defaultdict(lambda: {"total": 0, "meaningful": 0, "empty": 0})

    all_peer_results = []

    for peer_dir in sorted(peer_dirs):
        daily_data, summary, malformed, empty_events = load_peer_data(peer_dir)
        if daily_data is None and summary is None:
            continue

        username = peer_dir.name
        daily_count = len(daily_data) + len(empty_events) + len(malformed)
        if daily_data:
            dates = [d[0] for d in daily_data] + empty_events
        else:
            dates = empty_events

        total_daily_events = sum(d[1] for d in daily_data) if daily_data else 0
        level = summary.get("level", "unknown") if summary else "unknown"

        # 1. Low file count
        if daily_count < SUSPICIOUS_THRESHOLD:
            low_file_count.append((username, daily_count, level))

        # 2. Empty files
        if empty_events:
            peers_with_empty.append((username, len(empty_events), daily_count))
        if daily_count == len(empty_events) and daily_count > 0:
            peers_all_empty.append((username, daily_count, level))

        # 3. Date gaps (for peers with >30 files)
        if len(dates) > 30:
            gaps = find_date_gaps(dates, expected_weekdays)
            if gaps:
                peers_with_gaps.append((username, gaps, len(dates)))

        # 4. Suspicious: all zero events
        if daily_count > 0 and total_daily_events == 0:
            peers_zero_events.append((username, daily_count, level))

        # 4. Sudden stop: last date with events is well before Feb 22
        if daily_data and len(daily_data) >= 5:
            sorted_dates = sorted(d[0] for d in daily_data)
            last_date = sorted_dates[-1]
            if last_date in expected_weekdays:
                idx = expected_weekdays.index(last_date)
                # If last event date is 5+ weekdays before end, suspicious
                if idx < len(expected_weekdays) - 5:
                    peers_sudden_stop.append(
                        (username, last_date, expected_weekdays[-1])
                    )

        # 5. Summary vs daily
        if summary and "total_events" in summary:
            summary_total = summary["total_events"]
            if summary_total != total_daily_events:
                summary_mismatches.append(
                    (username, summary_total, total_daily_events, level)
                )

        # 6. Level distribution
        level_stats[level]["total"] += 1
        if total_daily_events > MIN_MEANINGFUL_EVENTS:
            level_stats[level]["meaningful"] += 1
        elif total_daily_events == 0 and daily_count > 0:
            level_stats[level]["empty"] += 1

        sources = get_sources_from_daily(daily_data) if daily_data else set()
        all_peer_results.append(
            {
                "username": username,
                "daily_count": daily_count,
                "total_events": total_daily_events,
                "empty_files": len(empty_events),
                "malformed": len(malformed),
                "level": level,
                "dates": sorted(set(dates)),
                "sources": sources,
            }
        )

    # 4b. Source count anomaly: peers with 1-2 sources when level has 4-5
    level_source_counts = defaultdict(list)
    for p in all_peer_results:
        if p["total_events"] > 0:  # Only peers with data
            level_source_counts[p["level"]].append(len(p["sources"]))
    level_median_sources = {
        lev: (sorted(c)[len(c) // 2] if c else 0)
        for lev, c in level_source_counts.items()
    }
    peers_few_sources = []
    for p in all_peer_results:
        if p["total_events"] > 0 and p["level"] in level_median_sources:
            median = level_median_sources[p["level"]]
            if median >= 4 and len(p["sources"]) <= 2:
                peers_few_sources.append(
                    (p["username"], len(p["sources"]), p["level"], median)
                )

    # 5. Summary vs daily - sample 10 random
    import random

    random.seed(42)
    sample_peers = random.sample(
        [
            p
            for p in all_peer_results
            if p["total_events"] > 0 or (summary and summary.get("total_events", 0) > 0)
        ],
        min(10, len(all_peer_results)),
    )
    # Actually we already have summary_mismatches - let's also verify 10 random peers
    sample_for_verify = random.sample(all_peer_results, min(10, len(all_peer_results)))
    sample_mismatches = []
    for p in sample_for_verify:
        summary_path = PEERS_DIR / p["username"] / "summary.json"
        if summary_path.exists():
            try:
                with open(summary_path) as fp:
                    s = json.load(fp)
                if s.get("total_events") != p["total_events"]:
                    sample_mismatches.append(
                        (p["username"], s.get("total_events"), p["total_events"])
                    )
            except Exception:
                pass

    # --- REPORT ---
    print("=" * 80)
    print("PEER BACKFILL AUDIT REPORT - Q1 2026 (Jan 1 - Feb 22)")
    print("=" * 80)

    print("\n## 1. DAILY FILE COUNT PER PEER (suspicious: <35 files)")
    print("-" * 60)
    if low_file_count:
        for username, count, level in sorted(low_file_count, key=lambda x: x[1]):
            print(
                f"  {username} ({level}): {count} files (expected ~{EXPECTED_WEEKDAYS})"
            )
        print(f"\n  Total: {len(low_file_count)} peers with <35 daily files")
    else:
        print("  None - all peers have >=35 daily files")

    print("\n## 2. EMPTY DAILY FILES (events array empty)")
    print("-" * 60)
    if peers_with_empty:
        # Show top 20 by empty count
        for username, empty_cnt, total in sorted(peers_with_empty, key=lambda x: -x[1])[
            :20
        ]:
            print(f"  {username}: {empty_cnt} empty files (of {total} total)")
        if len(peers_with_empty) > 20:
            print(f"  ... and {len(peers_with_empty) - 20} more")
        print(f"\n  Total: {len(peers_with_empty)} peers have at least one empty file")
    else:
        print("  None")

    print("\n## 3. PEERS WITH ALL FILES EMPTY (0 events)")
    print("-" * 60)
    if peers_all_empty:
        for username, count, level in peers_all_empty:
            print(f"  {username} ({level}): {count} files, 0 events in all")
        print(f"\n  Total: {len(peers_all_empty)} peers")
    else:
        print("  None")

    print("\n## 4. DATE GAPS (peers with >30 files, missing weekdays)")
    print("-" * 60)
    if peers_with_gaps:
        for username, gaps, total in peers_with_gaps[:15]:
            gap_str = ", ".join(gaps[:5]) + ("..." if len(gaps) > 5 else "")
            print(f"  {username}: {len(gaps)} missing dates: {gap_str}")
        if len(peers_with_gaps) > 15:
            print(f"  ... and {len(peers_with_gaps) - 15} more")
        print(f"\n  Total: {len(peers_with_gaps)} peers with date gaps")
    else:
        print("  None")

    print("\n## 4b. FEW SOURCES (1-2 when level median >=4)")
    print("-" * 60)
    if peers_few_sources:
        for username, n_src, level, median in peers_few_sources[:15]:
            print(f"  {username} ({level}): {n_src} sources (level median {median})")
        if len(peers_few_sources) > 15:
            print(f"  ... and {len(peers_few_sources) - 15} more")
        print(f"\n  Total: {len(peers_few_sources)} peers")
    else:
        print("  None")

    print("\n## 5. SUDDEN STOP (events end before Feb 22)")
    print("-" * 60)
    if peers_sudden_stop:
        for username, last_date, expected_end in peers_sudden_stop[:15]:
            print(
                f"  {username}: last event date {last_date} (expected through {expected_end})"
            )
        if len(peers_sudden_stop) > 15:
            print(f"  ... and {len(peers_sudden_stop) - 15} more")
        print(f"\n  Total: {len(peers_sudden_stop)} peers")
    else:
        print("  None")

    print("\n## 6. SUMMARY vs DAILY MISMATCH (total_events)")
    print("-" * 60)
    if summary_mismatches:
        for username, summary_val, daily_val, level in summary_mismatches[:15]:
            print(
                f"  {username} ({level}): summary={summary_val}, daily_sum={daily_val})"
            )
        if len(summary_mismatches) > 15:
            print(f"  ... and {len(summary_mismatches) - 15} more")
        print(f"\n  Total: {len(summary_mismatches)} peers with mismatch")
    else:
        print("  None")

    print("\n## 7. SAMPLE VERIFICATION (10 random peers)")
    print("-" * 60)
    if sample_mismatches:
        for username, summary_val, daily_val in sample_mismatches:
            print(f"  {username}: summary={summary_val}, daily_sum={daily_val}")
        print(f"\n  {len(sample_mismatches)} of 10 sampled peers have mismatch")
    else:
        print("  All 10 sampled peers: summary matches daily sum")

    print("\n## 8. LEVEL DISTRIBUTION")
    print("-" * 60)
    for level in sorted(level_stats.keys()):
        s = level_stats[level]
        print(
            f"  {level}: {s['total']} peers, {s['meaningful']} with >10 events, {s['empty']} effectively empty"
        )

    # Overall verdict
    print("\n" + "=" * 80)
    print("OVERALL VERDICT")
    print("=" * 80)

    failures = []
    if low_file_count:
        failures.append(f"{len(low_file_count)} peers with <35 daily files")
    if peers_all_empty:
        failures.append(f"{len(peers_all_empty)} peers with 0 events in all files")
    if peers_with_gaps:
        failures.append(f"{len(peers_with_gaps)} peers with date gaps")
    if summary_mismatches and len(summary_mismatches) > 5:
        failures.append(f"{len(summary_mismatches)} peers with summary/daily mismatch")

    if failures:
        print("\nVERDICT: INVALID CAPTURE")
        print("Evidence of failure:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("\nVERDICT: LIKELY VALID (minor issues only)")
        if summary_mismatches:
            print(
                f"  Note: {len(summary_mismatches)} summary/daily mismatches (may be stale summaries)"
            )
        if peers_with_empty:
            print(f"  Note: {len(peers_with_empty)} peers have some empty files")

    # Statistics
    total_peers = len(all_peer_results)
    avg_files = (
        sum(p["daily_count"] for p in all_peer_results) / total_peers
        if total_peers
        else 0
    )
    peers_full = sum(1 for p in all_peer_results if p["daily_count"] >= 35)
    peers_meaningful = sum(
        1 for p in all_peer_results if p["total_events"] > MIN_MEANINGFUL_EVENTS
    )

    print("\n## STATISTICS")
    print("-" * 60)
    print(f"  Total peers: {total_peers}")
    print(f"  Expected weekdays: {len(expected_weekdays)}")
    print(f"  Avg daily files per peer: {avg_files:.1f}")
    print(f"  Peers with >=35 files: {peers_full} ({100*peers_full/total_peers:.0f}%)")
    print(
        f"  Peers with >10 events: {peers_meaningful} ({100*peers_meaningful/total_peers:.0f}%)"
    )


if __name__ == "__main__":
    main()
