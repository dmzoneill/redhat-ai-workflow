---
description: Backfill missing performance data for the current quarter
---

Check for any missing weekdays this quarter and backfill the data.

This will:
1. Scan the current quarter for missing weekday files
2. Run data collection for each missing date
3. Update the quarter summary

Useful after vacation, sick days, or if the daily cron was missed.

@skill performance/backfill_missing.yaml
