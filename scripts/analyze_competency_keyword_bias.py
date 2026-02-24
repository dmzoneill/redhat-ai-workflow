#!/usr/bin/env python3
"""
Analyze competency keyword matching bias: self vs peer (simaishi).

Compares:
- Average competencies matched per event (points dict keys)
- Average signals per event (sum of signal_counts)
- Classification text length and keyword density
- Event type diversity
"""

import json
from collections import Counter
from pathlib import Path

SELF_DAILY = Path.home() / ".config/aa-workflow/performance/2026/q1/performance/daily"
PEER_DAILY = (
    Path.home()
    / ".config/aa-workflow/performance/2026/q1/performance/peers/simaishi/daily"
)

SAMPLE_DAYS = ["2026-01-05", "2026-01-13", "2026-01-22", "2026-01-26", "2026-02-02"]


def load_events(path: Path, date: str) -> list[dict]:
    f = path / f"{date}.json"
    if not f.exists():
        return []
    data = json.loads(f.read_text())
    return data.get("events", [])


def analyze_person(path: Path, label: str, dates: list[str]) -> dict:
    comps_per_event = []
    total_signals_per_event = []
    text_lengths = []
    event_types = []
    events_with_points = 0
    total_events = 0

    for date in dates:
        events = load_events(path, date)
        for ev in events:
            total_events += 1
            pts = ev.get("points", {})
            sig = ev.get("signal_counts", {})
            txt = ev.get("classification_text", "") or ""

            comps_per_event.append(len(pts))
            if pts:
                events_with_points += 1

            total_sigs = sum(v for v in sig.values() if isinstance(v, (int, float)))
            total_signals_per_event.append(total_sigs)

            text_lengths.append(len(txt))
            event_types.append(ev.get("type", "unknown"))

    n = len(comps_per_event)
    return {
        "label": label,
        "total_events": total_events,
        "events_with_points": events_with_points,
        "avg_comps_per_event": sum(comps_per_event) / n if n else 0,
        "avg_comps_per_scored_event": (
            sum(comps_per_event) / events_with_points if events_with_points else 0
        ),
        "avg_signals_per_event": sum(total_signals_per_event) / n if n else 0,
        "avg_text_length": sum(text_lengths) / n if n else 0,
        "event_type_counts": dict(Counter(event_types)),
        "event_type_diversity": len(set(event_types)),
        "comps_per_event_dist": comps_per_event,
        "text_lengths": text_lengths,
    }


def main():
    self_data = analyze_person(SELF_DAILY, "self", SAMPLE_DAYS)
    peer_data = analyze_person(PEER_DAILY, "simaishi", SAMPLE_DAYS)

    print("=" * 70)
    print("COMPETENCY KEYWORD MATCHING BIAS ANALYSIS")
    print("Self vs simaishi (PSE peer) - 5 sampled days")
    print("=" * 70)

    print("\n## 1. Average competencies matched per event")
    print(f"  Self:     {self_data['avg_comps_per_event']:.2f} competencies/event")
    print(f"  Simaishi: {peer_data['avg_comps_per_event']:.2f} competencies/event")
    ratio = (
        self_data["avg_comps_per_event"] / peer_data["avg_comps_per_event"]
        if peer_data["avg_comps_per_event"]
        else float("inf")
    )
    print(f"  Ratio (self/peer): {ratio:.2f}x")

    print("\n## 2. Average competencies per SCORED event (events with points > 0)")
    print(f"  Self:     {self_data['avg_comps_per_scored_event']:.2f}")
    print(f"  Simaishi: {peer_data['avg_comps_per_scored_event']:.2f}")

    print("\n## 3. Average total signals per event (sum of signal_counts)")
    print(f"  Self:     {self_data['avg_signals_per_event']:.1f} signals/event")
    print(f"  Simaishi: {peer_data['avg_signals_per_event']:.1f} signals/event")
    sig_ratio = (
        self_data["avg_signals_per_event"] / peer_data["avg_signals_per_event"]
        if peer_data["avg_signals_per_event"]
        else float("inf")
    )
    print(f"  Ratio (self/peer): {sig_ratio:.2f}x")

    print("\n## 4. Classification text analysis")
    print(
        f"  Avg length (chars) - Self: {self_data['avg_text_length']:.0f}, Simaishi: {peer_data['avg_text_length']:.0f}"
    )
    len_ratio = (
        self_data["avg_text_length"] / peer_data["avg_text_length"]
        if peer_data["avg_text_length"]
        else float("inf")
    )
    print(f"  Ratio (self/peer): {len_ratio:.2f}x")
    # Keyword density = signals / text_length (signals per 100 chars)
    self_kw_density = (
        100 * self_data["avg_signals_per_event"] / self_data["avg_text_length"]
        if self_data["avg_text_length"]
        else 0
    )
    peer_kw_density = (
        100 * peer_data["avg_signals_per_event"] / peer_data["avg_text_length"]
        if peer_data["avg_text_length"]
        else 0
    )
    print(
        f"  Keyword density (signals/100 chars) - Self: {self_kw_density:.2f}, Simaishi: {peer_kw_density:.2f}"
    )

    print("\n## 5. Event type diversity")
    print(
        f"  Unique event types - Self: {self_data['event_type_diversity']}, Simaishi: {peer_data['event_type_diversity']}"
    )
    print("\n  Event type distribution (self):")
    for t, c in sorted(self_data["event_type_counts"].items(), key=lambda x: -x[1]):
        print(f"    {t}: {c}")
    print("\n  Event type distribution (simaishi):")
    for t, c in sorted(peer_data["event_type_counts"].items(), key=lambda x: -x[1]):
        print(f"    {t}: {c}")

    print("\n## 6. Event counts")
    print(f"  Self total events (5 days): {self_data['total_events']}")
    print(f"  Simaishi total events (5 days): {peer_data['total_events']}")
    print(f"  Self events with points: {self_data['events_with_points']}")
    print(f"  Simaishi events with points: {peer_data['events_with_points']}")

    # Competency breadth distribution
    print("\n## 7. Competencies-per-event distribution")
    self_dist = Counter(self_data["comps_per_event_dist"])
    peer_dist = Counter(peer_data["comps_per_event_dist"])
    for k in sorted(set(self_dist) | set(peer_dist)):
        print(f"  {k} comps: self={self_dist.get(k,0)}, simaishi={peer_dist.get(k,0)}")


if __name__ == "__main__":
    main()
