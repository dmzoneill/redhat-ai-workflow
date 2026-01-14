# /review

> **Description:** Review a specific GitLab Merge Request with detailed analysis.

## Overview

**Description:** Review a specific GitLab Merge Request with detailed analysis.

**Underlying Skill:** `review_pr`

This command is a wrapper that calls the `review_pr` skill. For detailed process information, see [skills/review_pr.md](../skills/review_pr.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `mr_id` | No | - |

## Usage

### Examples

```bash
skill_run("review_pr", '{"mr_id": 1450}')
```

```bash
skill_run("review_pr", '{"mr_id": 1450, "run_tests": true}')
  ```text

**What it does:**

1. **Fetches MR details** - Title, description, author, status
2. **Analyzes changes** - Files modified, additions/deletions
3. **Checks pipeline status** - CI/CD results
4. **Reviews code quality** - Looks for common issues
5. **Optionally runs tests** - Local pytest execution
6. **Suggests action** - Approve, request changes, or needs discussion

**Example:**
```

```bash
This runs:
```

## Process Flow

This command invokes the `review_pr` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /review]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call review_pr skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```

For detailed step-by-step process, see the [review_pr skill documentation](../skills/review_pr.md).

## Details


## Related Commands

_(To be determined based on command relationships)_
