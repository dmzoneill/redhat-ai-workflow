---
name: release-aa-backend-prod
description: "Release automation-analytics-backend to production."
arguments:
  - name: commit
---
# Release AA Backend to Prod

Release automation-analytics-backend to production.

## Instructions

```text
skill_run("release_aa_backend_prod", '{}')
```

## What It Does

1. Checks Konflux build status
2. Validates stage deployment is healthy
3. Creates app-interface MR for production
4. Monitors the rollout

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `commit` | Specific commit SHA to release | No (latest main) |
| `dry_run` | Preview without creating MR | No (default: false) |

## Examples

```bash
# Release latest main to prod
skill_run("release_aa_backend_prod", '{}')

# Release specific commit
skill_run("release_aa_backend_prod", '{"commit": "abc123def456"}')
```

## Prerequisites

- Stage deployment healthy
- All tests passed
- Konflux build completed
