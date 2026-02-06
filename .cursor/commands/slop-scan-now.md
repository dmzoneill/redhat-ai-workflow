# Slop Scan Now

Trigger a slop code quality scan via D-Bus.

## Instructions

```text
skill_run("slop_scan_now", '{"wait_for_completion": "", "timeout_seconds": ""}')
```

## What It Does

Trigger a slop code quality scan via D-Bus.

The slop daemon must be running (systemctl --user start bot-slop).
This skill sends a scan_now command to the daemon, which runs all
analysis loops (security, dead code, complexity, etc.).

Use this to refresh findings before running slop_fix.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `wait_for_completion` | If true, wait for scan to complete before returning (default: True) | No |
| `timeout_seconds` | Maximum time to wait for scan completion (default 10 minutes) (default: 600) | No |
