---
name: check-my-prs
description: "Check status of your open merge requests."
---
# Check My PRs

Check status of your open merge requests.

## Instructions

```text
skill_run("check_my_prs", '{}')
```

## What It Does

1. Lists your open MRs
2. Shows pipeline status for each
3. Highlights MRs with feedback
4. Shows approval status

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `project` | GitLab project | No (auto-detected) |

## Examples

```bash
# Check your MRs
skill_run("check_my_prs", '{}')
```

## Output

- MR title and ID
- Pipeline status (passed/failed/running)
- Review comments count
- Approval status
