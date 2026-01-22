# Create Jira Issue

Create a new Jira issue.

## Instructions

```text
skill_run("create_jira_issue", '{"issue_type": "$TYPE", "summary": "$SUMMARY"}')
```

## What It Does

1. Creates a new Jira issue
2. Sets required fields based on type
3. Returns the new issue key

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `issue_type` | Type: bug, story, task, epic | Yes |
| `summary` | Issue title | Yes |
| `description` | Issue description | No |
| `project` | Jira project key | No (default: AAP) |
| `labels` | Comma-separated labels | No |

## Examples

```bash
# Create a bug
skill_run("create_jira_issue", '{"issue_type": "bug", "summary": "API returns 500 on invalid input"}')

# Create a story
skill_run("create_jira_issue", '{"issue_type": "story", "summary": "Add user authentication", "description": "Implement OAuth2 login"}')

# Create with labels
skill_run("create_jira_issue", '{"issue_type": "task", "summary": "Update dependencies", "labels": "tech-debt,maintenance"}')
```
