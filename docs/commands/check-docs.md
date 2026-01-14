# /check-docs

> Check repository documentation for staleness

## Overview

Check repository documentation for staleness

**Underlying Skill:** `update_docs`

This command is a wrapper that calls the `update_docs` skill. For detailed process information, see [skills/update_docs.md](../skills/update_docs.md).

## Arguments

No arguments required.

## Usage

### Examples

```bash
skill_run("update_docs", '{"repo": ".", "check_only": true}')
```

```bash
skill_run("update_docs", '{"repo_name": "automation-analytics-backend", "check_only": true}')
```

## Process Flow

This command invokes the `update_docs` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /check-docs]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call update_docs skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [update_docs skill documentation](../skills/update_docs.md).

## Details

## What This Does

1. Scans for changed files in the current branch
2. Checks README.md for broken links
3. Reviews API docs if endpoints changed
4. Checks mermaid diagrams if architecture changed
5. Reports issues and suggestions

## Usage

Run the update_docs skill to check documentation:

```
skill_run("update_docs", '{"repo": ".", "check_only": true}')
```text

Or for a specific repository:

```
skill_run("update_docs", '{"repo_name": "automation-analytics-backend", "check_only": true}')
```

## Notes

- Only runs for repos with `docs.enabled=true` in config.json
- Integrated into `create_mr` and `mark_mr_ready` skills
- Use `check_only: true` to just check, `check_only: false` for suggestions


## Related Commands

_(To be determined based on command relationships)_
