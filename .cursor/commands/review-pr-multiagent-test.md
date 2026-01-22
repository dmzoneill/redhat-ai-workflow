# Review PR Multi-Agent Test

Test skill for multi-agent PR review functionality.

## Instructions

```text
skill_run("review_pr_multiagent_test", '{"mr_id": $MR_ID}')
```

## What It Does

Test version of the multi-agent review skill for development and debugging.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `mr_id` | Merge request ID | Yes |

## Examples

```bash
skill_run("review_pr_multiagent_test", '{"mr_id": 1450}')
```
