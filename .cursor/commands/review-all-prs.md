# Review All Open PRs

Review all open merge requests for a project.

## Instructions

```text
skill_run("review_all_prs", '{}')
```

## What It Does

1. Lists all open MRs for the project
2. Runs static analysis on each
3. Identifies MRs needing attention
4. Summarizes review status

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `project` | GitLab project to review | No (auto-detected) |
| `author` | Filter by author username | No |

## Examples

```bash
# Review all open MRs
skill_run("review_all_prs", '{}')

# Review specific author's MRs
skill_run("review_all_prs", '{"author": "jsmith"}')
```
