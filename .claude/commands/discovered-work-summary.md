---
name: discovered-work-summary
description: "Generate a summary of discovered work for daily standups or weekly reports."
arguments:
  - name: period
  - name: include_pending
  - name: include_synced
  - name: format
---
# Discovered Work Summary

Generate a summary of discovered work for daily standups or weekly reports.

## Instructions

```text
skill_run("discovered_work_summary", '{"period": "", "include_pending": "", "include_synced": "", "format": ""}')
```

## What It Does

Generate a summary of discovered work for daily standups or weekly reports.

This skill:
1. Retrieves discovered work from the specified time period
2. Groups by type, priority, and source
3. Lists Jira issues created
4. Provides statistics and trends

Can be called from standup_summary or weekly_summary skills.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `period` | Time period: 'daily' (1 day), 'weekly' (7 days), or number of days (default: daily) | No |
| `include_pending` | Include items not yet synced to Jira (default: True) | No |
| `include_synced` | Include items already synced to Jira (default: True) | No |
| `format` | Output format: 'markdown', 'slack', 'brief' (default: markdown) | No |
