# AA Jira MCP Server

MCP server for Jira issue tracking operations via the `rh-issue` CLI.

## Tools (23)

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
| `jira_set_status` | Transition issue status |
| `jira_assign` | Assign to user |
| `jira_unassign` | Remove assignee |
| `jira_add_comment` | Add comment |
| `jira_block` | Mark as blocked |
| `jira_unblock` | Remove block |
| `jira_add_to_sprint` | Add to sprint |
| `jira_remove_sprint` | Remove from sprint |
| `jira_create_issue` | Create new issue |
| `jira_clone_issue` | Clone existing issue |
| `jira_add_link` | Link issues |
| `jira_add_flag` | Add impediment flag |
| `jira_remove_flag` | Remove flag |
| `jira_open_browser` | Open in browser |

## Installation

```bash
cd mcp-servers/aa-jira
pip install -e .
```

## Prerequisites

- `rh-issue` CLI installed: `pip install rh-issue`
- `JIRA_JPAT` environment variable set with your Jira Personal Access Token

## Usage

### Cursor/MCP Config

```json
{
  "mcpServers": {
    "jira": {
      "command": "aa-jira"
    }
  }
}
```

## Authentication

Uses `JIRA_JPAT` environment variable (Personal Access Token for Red Hat Jira).

