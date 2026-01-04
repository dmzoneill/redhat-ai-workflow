# 📋 jira

> Jira issue tracking

## Overview

The `aa-jira` module provides tools for Jira operations including issue viewing, creation, transitions, and search.

## Tool Count

**25 tools**

## Tools

### Read Operations

| Tool | Description |
|------|-------------|
| `jira_view_issue` | View issue details |
| `jira_view_issue_json` | Get issue as JSON |
| `jira_search` | Search with JQL |
| `jira_list_issues` | List project issues |
| `jira_my_issues` | List your assigned issues |
| `jira_list_blocked` | List blocked issues |
| `jira_lint` | Check issue quality |

### Write Operations

| Tool | Description |
|------|-------------|
| `jira_create_issue` | Create new issue |
| `jira_set_status` | Transition issue status |
| `jira_assign` | Assign to user |
| `jira_unassign` | Remove assignee |
| `jira_add_comment` | Add comment |
| `jira_block` | Mark as blocked |
| `jira_unblock` | Remove block |
| `jira_add_to_sprint` | Add to sprint |
| `jira_remove_sprint` | Remove from sprint |
| `jira_clone_issue` | Clone existing issue |
| `jira_add_link` | Link issues |
| `jira_add_flag` | Add impediment flag |
| `jira_remove_flag` | Remove flag |
| `jira_open_browser` | Open in browser |

## Usage Examples

### View Issue

```python
jira_view_issue(issue_key="AAP-12345")
```

### Search Issues

```python
jira_search(
    jql="project = AAP AND status = 'In Progress' AND assignee = currentUser()",
    max_results=20
)
```

### Create Issue

```python
jira_create_issue(
    issue_data_json='{"summary": "New feature", "issuetype": {"name": "story"}}'
)
```

### Transition Status

```python
jira_set_status(issue_key="AAP-12345", status="In Progress")
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `JIRA_URL` | Yes | Jira instance URL |
| `JIRA_JPAT` | Yes | Jira Personal Access Token |

> Uses `rh-issue` CLI under the hood.

## Loaded By

- [👨‍💻 Developer Persona](../personas/developer.md)
- [🚨 Incident Persona](../personas/incident.md)
- [💬 Slack Persona](../personas/slack.md)

## Related Skills

- [start_work](../skills/start_work.md) - Gets and updates issues
- [close_issue](../skills/close_issue.md) - Closes issues
- [jira_hygiene](../skills/jira_hygiene.md) - Validates issues
- [create_jira_issue](../skills/create_jira_issue.md) - Creates issues
