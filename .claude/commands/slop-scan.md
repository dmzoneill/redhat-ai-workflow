---
name: slop-scan
description: "Run code quality analysis using the Slop Bot service."
arguments:
  - name: codebase_path
  - name: max_parallel
---
# Slop Scan

Run code quality analysis using the Slop Bot service.

## Instructions

```text
skill_run("slop_scan", '{"codebase_path": "", "max_parallel": ""}')
```

## What It Does

Run code quality analysis using the Slop Bot service.
Analyzes the codebase for code smells, complexity issues, and improvement opportunities.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `codebase_path` | Path to codebase to analyze (default: current workspace) | No |
| `max_parallel` | Maximum concurrent analysis loops (default: 3) | No |
