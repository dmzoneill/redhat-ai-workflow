---
name: release-to-prod
description: "Release a version to production environment."
arguments:
  - name: version
    required: true
---
# Release to Production

Release a version to production environment.

## Instructions

```text
skill_run("release_to_prod", '{"version": "$VERSION"}')
```

## What It Does

1. Validates the version exists
2. Checks all tests passed
3. Creates release notes
4. Triggers production deployment
5. Monitors rollout

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `version` | Version tag to release | Yes |
| `dry_run` | Preview without deploying | No (default: false) |

## Examples

```bash
# Release a version
skill_run("release_to_prod", '{"version": "v1.2.3"}')

# Dry run first
skill_run("release_to_prod", '{"version": "v1.2.3", "dry_run": true}')
```

## Prerequisites

- All CI checks passed
- Version tag exists
- Approval from release manager
