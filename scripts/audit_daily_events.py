#!/usr/bin/env python3
"""
Audit daily event files for QC performance system.
Extract all AAP-* and ANSTRAT-* issue keys, count events, sum points.
Compare categorized vs uncategorized.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

DAILY_DIR = Path.home() / ".config/aa-workflow/performance/2026/q1/performance/daily"

# Issues that ARE in the ANSTRAT hierarchy tree (categorized)
CATEGORIZED = {
    "AAP-53376",
    "AAP-65345",
    "AAP-64892",
    "AAP-65346",
    "AAP-65344",
    "AAP-64893",  # ANSTRAT-1500
    "AAP-62501",
    "AAP-58394",  # ANSTRAT-1859
    "AAP-41047",
    "AAP-61697",  # ANSTRAT-1859
}


def sum_points(points: dict) -> float:
    """Sum all point values in a points dict."""
    if not points or not isinstance(points, dict):
        return 0.0
    return sum(v for v in points.values() if isinstance(v, (int, float)))


def extract_item_id_keys(item_id: str) -> list[str]:
    """Extract AAP-* and ANSTRAT-* from item_id if it matches."""
    if not item_id or not isinstance(item_id, str):
        return []
    # Exact match for AAP-NNNNN or ANSTRAT-NNNN
    m = re.match(r"^(AAP-\d+|ANSTRAT-\d+)$", item_id.strip())
    if m:
        return [m.group(1)]
    return []


def extract_keys_from_text(text: str) -> list[str]:
    """Extract all AAP-* and ANSTRAT-* from free text (titles, etc)."""
    if not text or not isinstance(text, str):
        return []
    return re.findall(r"(?:AAP-\d+|ANSTRAT-\d+)", text)


def run_extraction(use_title: bool) -> dict:
    """Extract keys: use_title=True matches daemon (from title), False uses item_id."""
    by_key: dict[str, dict] = defaultdict(lambda: {"events": 0, "points": 0.0})
    for f in sorted(DAILY_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        for ev in data.get("events", []):
            pts = sum_points(ev.get("points", {}))
            if use_title:
                keys = extract_keys_from_text(ev.get("title", ""))
            else:
                keys = extract_item_id_keys(ev.get("item_id", ""))
            for k in keys:
                by_key[k]["events"] += 1
                by_key[k]["points"] += pts
    return dict(by_key)


def main():
    if not DAILY_DIR.exists():
        print(f"Directory not found: {DAILY_DIR}")
        return

    files = list(DAILY_DIR.glob("*.json"))
    print(f"Found {len(files)} daily event files\n")

    # Method 1: DAEMON LOGIC - extracts from title (daemon.py line 3356)
    print("=" * 60)
    print("METHOD 1: Daemon logic (keys from TITLE - what QC uses)")
    print("=" * 60)
    by_key = run_extraction(use_title=True)
    aap_keys = {k: v for k, v in by_key.items() if k.startswith("AAP-")}
    anstrat_keys = {k: v for k, v in by_key.items() if k.startswith("ANSTRAT-")}

    print(f"\nTotal unique AAP issue keys: {len(aap_keys)}")
    print(f"Total unique ANSTRAT keys: {len(anstrat_keys)}")

    aap_sorted = sorted(aap_keys.items(), key=lambda x: -x[1]["points"])
    print("\n--- All AAP keys with event count and points ---")
    for k, v in aap_sorted:
        cat = "categorized" if k in CATEGORIZED else "UNCATEGORIZED"
        print(f"  {k}: {v['events']} events, {v['points']:.1f} pts [{cat}]")

    categorized_issues = [k for k in aap_keys if k in CATEGORIZED]
    uncategorized_issues = [k for k in aap_keys if k not in CATEGORIZED]
    uncat_points = sum(by_key[k]["points"] for k in uncategorized_issues)

    print("\n--- Summary (title-based) ---")
    print(f"Categorized ({len(categorized_issues)}): {sorted(categorized_issues)}")
    print(
        f"Uncategorized ({len(uncategorized_issues)}): {sorted(uncategorized_issues)}"
    )
    print(f"Uncategorized points: {uncat_points:.0f}")

    print("\n--- Match check (expected: 13 issues, 295 points) ---")
    match = len(uncategorized_issues) == 13 and abs(uncat_points - 295) < 1
    print(
        f"  Found: {len(uncategorized_issues)} issues, {uncat_points:.0f} points -> {'MATCH' if match else 'MISMATCH'}"
    )

    # Method 2: title + classification_text (broader - any key mention)
    print("\n" + "=" * 60)
    print("METHOD 2: title + classification_text (broader extraction)")
    print("=" * 60)
    by_both: dict[str, dict] = defaultdict(lambda: {"events": 0, "points": 0.0})
    for f in sorted(DAILY_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        for ev in data.get("events", []):
            pts = sum_points(ev.get("points", {}))
            text = (
                (ev.get("title", "") or "")
                + " "
                + (ev.get("classification_text", "") or "")
            )
            keys = extract_keys_from_text(text)
            for k in keys:
                by_both[k]["events"] += 1
                by_both[k]["points"] += pts
    aap_both = {k: v for k, v in by_both.items() if k.startswith("AAP-")}
    uncat_both = [k for k in aap_both if k not in CATEGORIZED]
    uncat_both_pts = sum(by_both[k]["points"] for k in uncat_both)
    print(f"Uncategorized: {len(uncat_both)} issues, {uncat_both_pts:.0f} pts")
    extra = set(uncat_both) - set(uncategorized_issues)
    if extra:
        print(f"  Extra vs title-only: {sorted(extra)}")

    # Method 3: item_id only (for comparison)
    print("\n" + "=" * 60)
    print("METHOD 3: item_id only (for comparison)")
    print("=" * 60)
    by_item = run_extraction(use_title=False)
    aap_item = {k: v for k, v in by_item.items() if k.startswith("AAP-")}
    uncat_item = [k for k in aap_item if k not in CATEGORIZED]
    uncat_item_pts = sum(by_item[k]["points"] for k in uncat_item)
    print(f"Uncategorized: {len(uncat_item)} issues, {uncat_item_pts:.0f} pts")


if __name__ == "__main__":
    main()
