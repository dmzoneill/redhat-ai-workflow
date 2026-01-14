# /review-mr

> Quick code review of a Merge Request - checks format, description, pipelines, and code patterns.

## Overview

Quick code review of a Merge Request - checks format, description, pipelines, and code patterns.

**Underlying Skill:** `review_pr`

This command is a wrapper that calls the `review_pr` skill. For detailed process information, see [skills/review_pr.md](../skills/review_pr.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `mr_id` | No | - |

## Usage

### Examples

```bash
skill_run("review_pr", '{"mr_id": $MR_ID}')
```

```bash
# By MR ID
skill_run("review_pr", '{"mr_id": 1450}')

# By Jira key (finds associated MR)
skill_run("review_pr", '{"issue_key": "AAP-60420"}')

# By GitLab URL
skill_run("review_pr", '{"url": "https://gitlab.cee.redhat.com/automation-analytics/automation-analytics-backend/-/merge_requests/1450"}')
```

## Process Flow

This command invokes the `review_pr` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /review-mr]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call review_pr skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [review_pr skill documentation](../skills/review_pr.md).

## Details

## Instructions

Run a static analysis review (no local tests):

```
skill_run("review_pr", '{"mr_id": $MR_ID}')
```

This will:
1. Fetch MR details from GitLab
2. Extract and validate Jira key from title
3. Check commit format against `config.json` pattern
4. Verify MR description is adequate
5. Check GitLab and Konflux pipeline status
6. Analyze code for security, memory leaks, race conditions
7. Auto-approve or post feedback based on findings

## Examples

```bash
# By MR ID
skill_run("review_pr", '{"mr_id": 1450}')

# By Jira key (finds associated MR)
skill_run("review_pr", '{"issue_key": "AAP-60420"}')

# By GitLab URL
skill_run("review_pr", '{"url": "https://gitlab.cee.redhat.com/automation-analytics/automation-analytics-backend/-/merge_requests/1450"}')
```


## Related Commands

_(To be determined based on command relationships)_
