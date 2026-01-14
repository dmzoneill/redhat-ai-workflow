# Check My PRs

Review status of your open merge requests.

## Instructions

```text
skill_run("check_my_prs", '{}')
```

## What It Does

1. Lists all your open MRs across projects
2. Shows CI/pipeline status for each
3. Checks for new comments or review feedback
4. Identifies MRs ready to merge
5. Flags stale MRs needing attention

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `project` | Specific project to check | All projects |
| `include_drafts` | Include draft MRs | `true` |

## Examples

```bash
# Check all your MRs
skill_run("check_my_prs", '{}')

# Check specific project
skill_run("check_my_prs", '{"project": "automation-analytics-backend"}')
```
