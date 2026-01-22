---
name: scan-vulnerabilities
description: "Scan code for security vulnerabilities."
arguments:
  - name: severity
---
# Scan Vulnerabilities

Scan code for security vulnerabilities.

## Instructions

```text
skill_run("scan_vulnerabilities", '{}')
```

## What It Does

1. Runs security scanners on the codebase
2. Checks for known CVEs in dependencies
3. Identifies potential security issues
4. Provides remediation suggestions

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `project` | Project to scan | No (auto-detected) |
| `severity` | Minimum severity to report | No (default: medium) |

## Examples

```bash
# Scan current project
skill_run("scan_vulnerabilities", '{}')

# Only high/critical issues
skill_run("scan_vulnerabilities", '{"severity": "high"}')
```
