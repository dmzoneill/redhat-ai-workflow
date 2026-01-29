# Backfill Missing

Find and backfill missing days in the current quarter.

## Instructions

```text
skill_run("performance/backfill_missing", '{"max_days": ""}')
```

## What It Does

Find and backfill missing days in the current quarter.

Scans for weekdays without performance data and runs
collection for each missing date.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `max_days` | Maximum number of days to backfill in one run (default: 10) | No |
