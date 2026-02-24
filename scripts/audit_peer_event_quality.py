#!/usr/bin/env python3
"""
Audit peer event quality and source coverage for Q1 2026 backfill.
Checks: source coverage by level, event content quality, scoring, meeting/gdrive, cross-peer consistency.
"""
import json
from collections import defaultdict
from pathlib import Path

PEERS_DIR = Path.home() / ".config/aa-workflow/performance/2026/q1/performance/peers"
SELF_SUMMARY = (
    Path.home() / ".config/aa-workflow/performance/2026/q1/performance/summary.json"
)
SELF_DAILY = Path.home() / ".config/aa-workflow/performance/2026/q1/performance/daily"


def load_json(p: Path):
    with open(p) as f:
        return json.load(f)


def main():
    benchmarks = load_json(PEERS_DIR / "benchmarks.json")
    self_summary = load_json(SELF_SUMMARY)

    self_sources = set(self_summary.get("event_counts_by_source", {}).keys())
    self_counts = self_summary.get("event_counts_by_source", {})
    print("=" * 80)
    print("PEER EVENT QUALITY & SOURCE COVERAGE AUDIT - Q1 2026")
    print("=" * 80)

    print("\n## 1. SELF BASELINE")
    print("-" * 60)
    print(f"Self sources: {sorted(self_sources)}")
    print(f"Self event counts: {self_counts}")
    print(f"Self total_events: {self_summary.get('total_events')}")

    # Build peer details
    peer_details = {}
    for entry in PEERS_DIR.iterdir():
        if not entry.is_dir() or entry.name == "benchmarks.json":
            continue
        summary_path = entry / "summary.json"
        if not summary_path.exists():
            continue
        try:
            s = load_json(summary_path)
        except Exception as e:
            print(f"  ERROR reading {entry.name}: {e}")
            continue
        username = s.get("username", entry.name)
        level = s.get("level", "unknown")
        sources = set(s.get("event_counts_by_source", {}).keys())
        total = s.get("total_events", 0)
        counts = s.get("event_counts_by_source", {})
        peer_details[username] = {
            "level": level,
            "sources": sources,
            "total_events": total,
            "event_counts_by_source": counts,
        }

    # Source coverage by level
    level_sources = defaultdict(lambda: defaultdict(int))
    level_peer_count = defaultdict(int)
    for u, d in peer_details.items():
        level = d["level"]
        level_peer_count[level] += 1
        for src in d["sources"]:
            level_sources[level][src] += 1

    peer_expected = self_sources - {"session"}  # session is local-only
    print("\n## 2. SOURCE COVERAGE BY LEVEL")
    print("-" * 60)
    for level in sorted(level_sources.keys()):
        n = level_peer_count[level]
        print(f"\n{level.upper()} ({n} peers):")
        for src in sorted(peer_expected):
            count = level_sources[level].get(src, 0)
            pct = 100 * count / n if n else 0
            status = "OK" if count == n else ("PARTIAL" if count > 0 else "MISSING")
            print(f"  {src}: {count}/{n} ({pct:.0f}%) {status}")

    # Peers missing sources (sample)
    missing_gdrive = [
        u for u, d in peer_details.items() if "gdrive" not in d["sources"]
    ]
    missing_meeting = [
        u for u, d in peer_details.items() if "meeting" not in d["sources"]
    ]
    print(
        f"\nPeers missing gdrive: {len(missing_gdrive)} (expected: peers use shared drive, not all have)"
    )
    print(
        f"Peers missing meeting: {len(missing_meeting)} (sample: {missing_meeting[:5]})"
    )

    # 3. Event content quality - 5 peers >100 events from different levels
    print("\n## 3. EVENT CONTENT QUALITY (5 peers >100 events)")
    print("-" * 60)
    by_level = defaultdict(list)
    for u, d in peer_details.items():
        if d["total_events"] > 100:
            by_level[d["level"]].append((u, d["total_events"]))

    sample_peers = []
    for level in ["ase", "se", "sse", "pse", "spse", "de"]:
        if by_level.get(level):
            top = max(by_level[level], key=lambda x: x[1])
            sample_peers.append((level, top[0], top[1]))
    sample_peers = sample_peers[:5]

    for level, username, total in sample_peers:
        daily_dir = PEERS_DIR / username / "daily"
        if not daily_dir.exists():
            print(f"  {username} ({level}): no daily dir")
            continue
        days = sorted([f.stem for f in daily_dir.glob("*.json")])
        issues = []
        for d in days[:3]:
            try:
                day_data = load_json(daily_dir / f"{d}.json")
            except Exception as e:
                issues.append(f"{d}: read error")
                continue
            events = day_data.get("events", [])
            for i, ev in enumerate(events[:10]):
                if not all(k in ev for k in ["title", "source", "type"]):
                    issues.append(f"{d} ev{i}: missing title/source/type")
                if ev.get("source") == "git" and "item_id" not in ev:
                    issues.append(f"{d} ev{i}: git without item_id")
            ids = [e.get("id") for e in events if e.get("id")]
            if len(ids) != len(set(ids)):
                issues.append(f"{d}: duplicate event ids")
        print(
            f"  {username} ({level}, {total} ev): {len(days)} days, issues={issues[:5] or 'none'}"
        )

    # 4. Meeting audit
    print("\n## 4. MEETING EVENT AUDIT")
    print("-" * 60)
    meeting_peers = [
        (u, d["event_counts_by_source"].get("meeting", 0))
        for u, d in peer_details.items()
    ]
    meeting_peers = sorted(meeting_peers, key=lambda x: -x[1])
    print(f"Self: {self_counts.get('meeting', 0)} meeting events")
    print(f"Peers with meetings: {sum(1 for _, c in meeting_peers if c > 0)}")
    print(f"Top 5: {meeting_peers[:5]}")

    for username, count in meeting_peers[:5]:
        if count == 0:
            continue
        daily_dir = PEERS_DIR / username / "daily"
        samples = []
        for p in sorted(daily_dir.glob("*.json"))[:15]:
            try:
                day = load_json(p)
                for e in day.get("events", []):
                    if e.get("source") == "meeting":
                        samples.append(
                            {
                                "date": p.stem,
                                "title": (e.get("title") or "")[:55],
                                "type": e.get("type"),
                                "n": e.get("meeting_attendee_count"),
                            }
                        )
                        if len(samples) >= 5:
                            break
            except Exception:
                pass
            if len(samples) >= 5:
                break
        print(f"\n  {username} ({count} meetings):")
        for m in samples[:5]:
            print(
                f"    {m['date']} | {m['title']}... | type={m['type']} attendees={m['n']}"
            )

    # 5. GDrive audit
    print("\n## 5. GDRIVE EVENT AUDIT")
    print("-" * 60)
    gdrive_peers = [
        (u, d["event_counts_by_source"].get("gdrive", 0))
        for u, d in peer_details.items()
        if d["event_counts_by_source"].get("gdrive", 0) > 0
    ]
    print(f"Self: {self_counts.get('gdrive', 0)} gdrive events")
    print(f"Peers with gdrive: {len(gdrive_peers)}")
    if gdrive_peers:
        print(f"Peers: {gdrive_peers[:10]}")
        for username, _ in gdrive_peers[:3]:
            daily_dir = PEERS_DIR / username / "daily"
            for p in sorted(daily_dir.glob("*.json")):
                try:
                    day = load_json(p)
                    for e in day.get("events", []):
                        if e.get("source") == "gdrive":
                            print(
                                f"  Sample: {username} | {str(e.get('title',''))[:70]} | type={e.get('type')}"
                            )
                            break
                except Exception:
                    pass
    else:
        print(
            "  No peers have gdrive events - possible collection gap for shared drives"
        )

    # 6. Cross-peer consistency
    print("\n## 6. CROSS-PEER CONSISTENCY (high vs low at same level)")
    print("-" * 60)
    for level in ["pse", "sse"]:
        at_level = [(u, d) for u, d in peer_details.items() if d["level"] == level]
        if len(at_level) < 2:
            continue
        sorted_peers = sorted(at_level, key=lambda x: x[1]["total_events"])
        low, high = sorted_peers[0], sorted_peers[-1]
        print(f"\n{level.upper()}:")
        print(
            f"  LOW:  {low[0]} - {low[1]['total_events']} ev, sources: {sorted(low[1]['sources'])}"
        )
        print(
            f"  HIGH: {high[0]} - {high[1]['total_events']} ev, sources: {sorted(high[1]['sources'])}"
        )
        missing = high[1]["sources"] - low[1]["sources"]
        if missing:
            print(f"  LOW missing vs HIGH: {missing}")

    # 7. Scoring sanity
    print("\n## 7. SCORING SANITY (git commit points)")
    print("-" * 60)
    self_git_sample = None
    if SELF_DAILY.exists():
        for p in sorted(SELF_DAILY.glob("*.json"))[:5]:
            try:
                day = load_json(p)
                for e in day.get("events", []):
                    if e.get("source") == "git" and e.get("type") == "commit":
                        pts = e.get("points", {})
                        total = sum(pts.values()) if pts else 0
                        self_git_sample = (e.get("title", "")[:50], pts, total)
                        break
            except Exception:
                pass
            if self_git_sample:
                break
    if self_git_sample:
        print(
            f"  Self git commit: {self_git_sample[0]}... | points={self_git_sample[1]} total={self_git_sample[2]}"
        )

    for username in ["daoneill", "bcoca", "bthomass", "drodowic"]:
        daily_dir = PEERS_DIR / username / "daily"
        if not daily_dir.exists():
            continue
        for p in sorted(daily_dir.glob("*.json"))[:5]:
            try:
                day = load_json(p)
                for e in day.get("events", []):
                    if e.get("source") == "git" and e.get("type") == "commit":
                        pts = e.get("points", {})
                        total = sum(pts.values()) if pts else 0
                        print(
                            f"  Peer {username}: {str(e.get('title',''))[:50]}... | points={pts} total={total}"
                        )
                        break
            except Exception:
                pass
            break

    print("\n" + "=" * 80)
    print("END AUDIT")
    print("=" * 80)


if __name__ == "__main__":
    main()
