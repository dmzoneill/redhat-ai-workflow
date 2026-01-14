---
name: release-prod
description: "Guide you through promoting stage → production."
arguments:
  - name: commit_sha
---
# 🚀 Release to Production

Guide you through promoting stage → production.

## Instructions

```text
skill_run("release_aa_backend_prod", '{"commit_sha": "abc123..."}')
```

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `commit_sha` | Git commit SHA to release (required) | - |
| `release_date` | Target release date | Today |
| `include_billing` | Include billing component | `false` |

## Examples

```bash
# Release main component
skill_run("release_aa_backend_prod", '{"commit_sha": "8d23cab1234567890abcdef..."}')

# Release with billing
skill_run("release_aa_backend_prod", '{"commit_sha": "8d23cab...", "include_billing": true}')

# Schedule for specific date
skill_run("release_aa_backend_prod", '{"commit_sha": "8d23cab...", "release_date": "2025-01-15"}')
```

## What It Does

1. Validates the commit SHA exists in stage
2. Checks Quay for the built image
3. Updates app-interface with new SHA
4. Creates MR in app-interface repo
5. Provides review checklist
6. Tracks deployment status

## Prerequisites

- Commit must be deployed and tested in stage
- Image must exist in Quay
- You must have app-interface repo access

## Checklist Before Release

- [ ] Stage deployment verified
- [ ] No firing alerts in stage
- [ ] Key features tested
- [ ] Team notified
- [ ] Rollback plan ready
