# /release-prod

> Guide you through promoting stage → production.

## Overview

Guide you through promoting stage → production.

**Underlying Skill:** `release_aa_backend_prod`

This command is a wrapper that calls the `release_aa_backend_prod` skill. For detailed process information, see [skills/release_aa_backend_prod.md](../skills/release_aa_backend_prod.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `commit_sha` | No | - |

## Usage

### Examples

```bash
skill_run("release_aa_backend_prod", '{"commit_sha": "abc123..."}')
```

```bash
# Release main component
skill_run("release_aa_backend_prod", '{"commit_sha": "8d23cab1234567890abcdef..."}')

# Release with billing
skill_run("release_aa_backend_prod", '{"commit_sha": "8d23cab...", "include_billing": true}')

# Schedule for specific date
skill_run("release_aa_backend_prod", '{"commit_sha": "8d23cab...", "release_date": "2025-01-15"}')
```

## Process Flow

This command invokes the `release_aa_backend_prod` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /release-prod]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call release_aa_backend_prod skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [release_aa_backend_prod skill documentation](../skills/release_aa_backend_prod.md).

## Details

## Instructions

```
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


## Related Commands

_(To be determined based on command relationships)_
