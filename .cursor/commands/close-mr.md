# Close MR

Close a merge request and update linked Jira.

## Instructions

```text
skill_run("close_mr", '{"mr_id": $MR_ID, "project": "$PROJECT"}')
```

## What It Does

1. Gets MR details and linked Jira
2. Closes the MR (not merge)
3. Transitions Jira issue appropriately
4. Adds closure comment with reason

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mr_id` | MR ID to close | Required |
| `project` | GitLab project | Current repo |
| `reason` | Closure reason | Optional |

## Examples

```bash
# Close an MR
skill_run("close_mr", '{"mr_id": 1234}')

# Close with reason
skill_run("close_mr", '{"mr_id": 1234, "reason": "Superseded by !1235"}')
```

## Note

This **closes** (abandons) the MR, it does not merge it.
Use `/review-mr` and approve to merge.
