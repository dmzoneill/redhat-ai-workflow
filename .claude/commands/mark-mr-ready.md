---
name: mark-mr-ready
description: "Mark a draft merge request as ready for review."
arguments:
  - name: mr_id
    required: true
---
# Mark MR Ready

Mark a draft merge request as ready for review.

## Instructions

```text
skill_run("mark_mr_ready", '{"mr_id": $MR_ID}')
```

## What It Does

1. Removes draft status from MR
2. Optionally adds reviewers
3. Posts a comment notifying reviewers

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `mr_id` | Merge request ID | Yes |
| `project` | GitLab project | No (auto-detected) |
| `reviewers` | Comma-separated reviewer usernames | No |

## Examples

```bash
# Mark MR as ready
skill_run("mark_mr_ready", '{"mr_id": 1450}')

# Mark ready and add reviewers
skill_run("mark_mr_ready", '{"mr_id": 1450, "reviewers": "jsmith,jdoe"}')
```
