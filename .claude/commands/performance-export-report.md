---
name: performance-export-report
description: "Generate a comprehensive quarterly performance report."
arguments:
  - name: format
  - name: quarter
---
# Export Report

Generate a comprehensive quarterly performance report.

## Instructions

```text
skill_run("performance/export_report", '{"format": "", "quarter": ""}')
```

## What It Does

Generate a comprehensive quarterly performance report.

Includes:
- Overall progress and competency scores
- Quarterly question responses
- Highlights and evidence
- Areas for improvement

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `format` | Export format: markdown, json, or html (default: markdown) | No |
| `quarter` | Quarter to export (e.g., 'Q1 2026'). Defaults to current. | No |
