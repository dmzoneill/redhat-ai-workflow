# /hotfix

> Create an emergency hotfix from production.

## Overview

Create an emergency hotfix from production.

**Underlying Skill:** `hotfix`

This command is a wrapper that calls the `hotfix` skill. For detailed process information, see [skills/hotfix.md](../skills/hotfix.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `commit` | No | - |
| `version` | No | - |

## Usage

### Examples

```bash
skill_run("hotfix", '{"commit": "$COMMIT_SHA", "version": "$VERSION"}')
```

```bash
# Create hotfix
skill_run("hotfix", '{"commit": "abc1234", "version": "v1.2.3-hotfix1"}')

# From specific base
skill_run("hotfix", '{"commit": "abc1234", "version": "v1.2.3-hotfix1", "base_tag": "v1.2.3"}')
```

## Process Flow

This command invokes the `hotfix` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /hotfix]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call hotfix skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [hotfix skill documentation](../skills/hotfix.md).

## Details

## Instructions

```
skill_run("hotfix", '{"commit": "$COMMIT_SHA", "version": "$VERSION"}')
```

## What It Does

1. Fetches latest from origin
2. Creates hotfix branch from production tag
3. Cherry-picks the fix commit
4. Tags the hotfix version
5. Pushes branch and tag

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `commit` | Commit SHA to cherry-pick | Required |
| `version` | Hotfix version tag | Required |
| `base_tag` | Production tag to branch from | Latest release |

## Examples

```bash
# Create hotfix
skill_run("hotfix", '{"commit": "abc1234", "version": "v1.2.3-hotfix1"}')

# From specific base
skill_run("hotfix", '{"commit": "abc1234", "version": "v1.2.3-hotfix1", "base_tag": "v1.2.3"}')
```

## Next Steps

After hotfix is created:
1. Create MR from hotfix branch
2. Get emergency review
3. Merge and deploy
4. Consider backporting to main


## Related Commands

_(To be determined based on command relationships)_
