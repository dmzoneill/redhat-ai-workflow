---
name: check-mr-feedback
description: "Get review comments and feedback on a merge request."
arguments:
  - name: mr_id
    required: true
---
# Check MR Feedback

Get review comments and feedback on a merge request.

## Instructions

```text
skill_run("check_mr_feedback", '{"mr_id": $MR_ID}')
```

## What It Does

1. Fetches all comments on the MR
2. Filters out bot comments
3. Groups by reviewer
4. Highlights unresolved discussions

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `mr_id` | Merge request ID | Yes |
| `project` | GitLab project | No (auto-detected) |

## Examples

```bash
# Check feedback on MR
skill_run("check_mr_feedback", '{"mr_id": 1450}')
```
