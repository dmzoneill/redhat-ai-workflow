# Jira Integration

> Jira Cloud API integration architecture

## Diagram

```mermaid
graph TB
    subgraph Tools[Jira Tools]
        BASIC[aa_jira_basic<br/>Read operations]
        CORE[aa_jira_core<br/>Write operations]
        EXTRA[aa_jira_extra<br/>Advanced features]
    end

    subgraph Operations[Operations]
        VIEW[jira_view_issue]
        SEARCH[jira_search]
        TRANSITION[jira_transition]
        COMMENT[jira_add_comment]
        CREATE[jira_create_issue]
        ASSIGN[jira_assign]
    end

    subgraph API[Jira Cloud API]
        REST[REST API v3]
        AUTH[API Token Auth]
    end

    subgraph Config[Configuration]
        URL[jira_url]
        TOKEN[jira_token]
        USER[jira_user]
    end

    Tools --> Operations
    Operations --> REST
    REST --> AUTH
    Config --> AUTH
```

## API Flow

```mermaid
sequenceDiagram
    participant Tool as Jira Tool
    participant Client as HTTP Client
    participant Auth as Auth Handler
    participant API as Jira Cloud API

    Tool->>Client: Make request
    Client->>Auth: Get credentials
    Auth-->>Client: API token

    Client->>API: GET/POST /rest/api/3/...
    Note over Client,API: Authorization: Basic base64(user:token)

    API-->>Client: JSON response
    Client-->>Tool: Parsed data
```

## Tool Tiers

### Basic (Read-only)

| Tool | Description | Endpoint |
|------|-------------|----------|
| jira_view_issue | View issue details | GET /issue/{key} |
| jira_search | Search issues (JQL) | POST /search |
| jira_list_transitions | List available transitions | GET /issue/{key}/transitions |
| jira_get_comments | Get issue comments | GET /issue/{key}/comment |

### Core (Write)

| Tool | Description | Endpoint |
|------|-------------|----------|
| jira_transition | Change issue status | POST /issue/{key}/transitions |
| jira_add_comment | Add comment | POST /issue/{key}/comment |
| jira_assign | Assign issue | PUT /issue/{key}/assignee |
| jira_update_fields | Update fields | PUT /issue/{key} |

### Extra (Advanced)

| Tool | Description | Endpoint |
|------|-------------|----------|
| jira_create_issue | Create new issue | POST /issue |
| jira_link_issues | Link issues | POST /issueLink |
| jira_bulk_update | Bulk operations | POST /issue/bulk |

## Error Handling

```mermaid
flowchart TB
    REQUEST[API Request]
    CHECK{Response OK?}
    SUCCESS[Return data]
    ERROR{Error type?}
    AUTH_ERR[401: Re-authenticate]
    RATE_ERR[429: Retry with backoff]
    OTHER_ERR[Return error message]

    REQUEST --> CHECK
    CHECK -->|200-299| SUCCESS
    CHECK -->|Error| ERROR
    ERROR -->|401| AUTH_ERR
    ERROR -->|429| RATE_ERR
    ERROR -->|Other| OTHER_ERR
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic | `tool_modules/aa_jira/src/tools_basic.py` | Read tools |
| tools_core | `tool_modules/aa_jira/src/tools_core.py` | Write tools |
| tools_extra | `tool_modules/aa_jira/src/tools_extra.py` | Advanced tools |
| adapter | `tool_modules/aa_jira/src/adapter.py` | Memory adapter |

## Related Diagrams

- [Tool Tiers](../03-tools/tool-tiers.md)
- [Jira Tools](../03-tools/jira-tools.md)
- [Auth Flows](./auth-flows.md)
