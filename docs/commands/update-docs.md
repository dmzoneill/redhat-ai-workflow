# /update-docs

> Check and update repository documentation

## Overview

Check and update repository documentation

**Underlying Skill:** `update_docs`

This command is a wrapper that calls the `update_docs` skill. For detailed process information, see [skills/update_docs.md](../skills/update_docs.md).

## Arguments

No arguments required.

## Usage

### Examples

```bash
skill_run("update_docs", '{"check_only": true}')
```

```bash
skill_run("update_docs", '{"repo_name": "automation-analytics-backend", "check_only": true}')
```

```bash
skill_run("update_docs", '{"issue_key": "AAP-12345", "check_only": false}')
```

## Process Flow

This command invokes the `update_docs` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /update-docs]) --> VALIDATE[Validate Arguments]
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

Check documentation in current repo:

```
skill_run("update_docs", '{"check_only": true}')
```text

Check a specific repository:

```
skill_run("update_docs", '{"repo_name": "automation-analytics-backend", "check_only": true}')
```text

With issue key for potential commits:

```
skill_run("update_docs", '{"issue_key": "AAP-12345", "check_only": false}')
```

## Config

Requires `docs` config in the repository's config.json entry:

```json
"docs": {
  "enabled": true,
  "path": "docs/",
  "readme": "README.md",
  "api_docs": "docs/api/",
  "architecture": "docs/architecture/",
  "diagrams": ["docs/architecture/*.md"],
  "auto_update": true,
  "check_on_mr": true
}
```

## Integration

This skill is automatically run by:
- `create_mr` - checks docs before creating MR
- `mark_mr_ready` - checks docs before marking ready

Use `check_docs: false` to skip in those skills.


## Related Commands

_(To be determined based on command relationships)_
