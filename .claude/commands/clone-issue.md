---
name: clone-issue
description: "Clone an existing Jira issue."
arguments:
  - name: issue_key
---
# Clone Jira Issue

Clone an existing Jira issue.

## Instructions

```text
skill_run("clone_jira_issue", '{"issue_key": "$JIRA_KEY"}')
```

## What It Does

1. Reads source issue details
2. Creates clone with linked reference
3. Adds "clones" link to original
4. Optionally assigns to you

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `issue_key` | Source issue to clone | Required |
| `project` | Target project | Same as source |
| `assign_to_me` | Auto-assign clone | `true` |

## Examples

```bash
# Clone an issue
skill_run("clone_jira_issue", '{"issue_key": "AAP-61214"}')

# Clone to different project
skill_run("clone_jira_issue", '{"issue_key": "AAP-61214", "project": "RHCLOUD"}')
```
