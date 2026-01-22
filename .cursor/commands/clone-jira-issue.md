# Clone Jira Issue

Create a copy of an existing Jira issue.

## Instructions

```text
skill_run("clone_jira_issue", '{"issue_key": "$JIRA_KEY"}')
```

## What It Does

1. Fetches the original issue details
2. Creates a new issue with same fields
3. Links the clone to the original
4. Returns the new issue key

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `issue_key` | Issue to clone (e.g., AAP-12345) | Yes |
| `new_summary` | New summary for the clone | No |

## Examples

```bash
# Clone an issue
skill_run("clone_jira_issue", '{"issue_key": "AAP-12345"}')

# Clone with new summary
skill_run("clone_jira_issue", '{"issue_key": "AAP-12345", "new_summary": "Follow-up: Original task part 2"}')
```
