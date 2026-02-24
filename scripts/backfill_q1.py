#!/usr/bin/env python3
"""Backfill Q1 2026 daily performance data with all sources."""
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

from services.stats.collector import DataCollector

c = DataCollector()

cache_dir = Path.home() / ".config/aa-workflow/performance/2026/q1/performance"
for f in cache_dir.glob("gitlab_event_cache*.json"):
    os.utime(f)
for f in cache_dir.glob("github_cache*.json"):
    os.utime(f)

q_start = date(2026, 1, 1)
today = date.today()

all_weekdays = []
current = q_start
while current <= today:
    if current.weekday() < 5:
        all_weekdays.append(current)
    current += timedelta(days=1)

print(f"Backfilling {len(all_weekdays)} weekdays from {q_start} to {today}")
start_time = time.time()

for i, d in enumerate(all_weekdays):
    t0 = time.time()
    try:
        daily_data = c.collect_for_date(d)
        events = daily_data.get("events", [])
        sources = {}
        for e in events:
            s = e.get("source", "unknown")
            sources[s] = sources.get(s, 0) + 1
        elapsed_d = time.time() - t0
        print(
            f"  [{i+1}/{len(all_weekdays)}] {d}: "
            f"{len(events)} events ({elapsed_d:.1f}s) "
            f"{dict(sorted(sources.items()))}"
        )
    except Exception as e:
        elapsed_d = time.time() - t0
        print(f"  [{i+1}/{len(all_weekdays)}] {d}: FAILED ({elapsed_d:.1f}s): {e}")

elapsed = time.time() - start_time
print(f"\nBackfill complete in {elapsed:.1f}s")
