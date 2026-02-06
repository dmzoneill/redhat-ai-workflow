# Jira Tools

> aa_jira module for Jira Cloud integration

## Diagram

```mermaid
classDiagram
    class JiraBasic {
        +jira_view_issue(key): dict
        +jira_search(jql, max): list
        +jira_list_projects(): list
        +jira_get_transitions(key): list
        +jira_get_comments(key): list
    }

    class JiraCore {
        +jira_create_issue(project, type, summary, desc): dict
        +jira_update_issue(key, fields): dict
        +jira_transition(key, status): dict
        +jira_add_comment(key, comment): dict
        +jira_assign(key, assignee): dict
        +jira_link_issues(from, to, type): dict
    }

    class JiraExtra {
        +jira_bulk_update(jql, fields): dict
        +jira_clone_issue(key, project): dict
        +jira_get_sprint(board): dict
        +jira_move_to_sprint(key, sprint): dict
        +jira_get_worklog(key): list
        +jira_add_worklog(key, time): dict
    }

    class JiraAdapter {
        +query(question): list
        +get_issue(key): dict
        +search(jql): list
    }

    JiraBasic <|-- JiraCore
    JiraCore <|-- JiraExtra
    JiraAdapter --> JiraBasic : uses
```

## API Flow

```mermaid
sequenceDiagram
    participant Tool as Jira Tool
    participant Client as HTTP Client
    participant Jira as Jira Cloud API
    participant Cache as Response Cache

    Tool->>Cache: Check cache
    
    alt Cache hit
        Cache-->>Tool: Cached response
    else Cache miss
        Tool->>Client: Build request
        Client->>Jira: REST API call
        Jira-->>Client: JSON response
        Client-->>Tool: Parsed response
        Tool->>Cache: Store in cache
    end

    Tool-->>Tool: Format for Claude
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_jira/src/` | Read operations |
| tools_core.py | `tool_modules/aa_jira/src/` | Write operations |
| tools_extra.py | `tool_modules/aa_jira/src/` | Advanced operations |
| adapter.py | `tool_modules/aa_jira/src/` | Memory adapter |
| server.py | `tool_modules/aa_jira/src/` | Standalone server |

## Tool Summary

| Tool | Tier | Description |
|------|------|-------------|
| `jira_view_issue` | basic | View issue details |
| `jira_search` | basic | Search with JQL |
| `jira_list_projects` | basic | List accessible projects |
| `jira_get_transitions` | basic | Get available transitions |
| `jira_create_issue` | core | Create new issue |
| `jira_update_issue` | core | Update issue fields |
| `jira_transition` | core | Change issue status |
| `jira_add_comment` | core | Add comment |
| `jira_bulk_update` | extra | Bulk update issues |
| `jira_clone_issue` | extra | Clone issue |

## Configuration

```json
{
  "jira": {
    "url": "https://issues.redhat.com",
    "project": "AAP",
    "token_env": "JIRA_JPAT"
  }
}
```

## Authentication

```mermaid
flowchart TB
    subgraph Auth[Authentication]
        ENV[JIRA_JPAT env var]
        KEYRING[System keyring]
        CONFIG[config.json]
    end

    subgraph Request[Request Building]
        HEADERS[Authorization header]
        URL[API URL]
    end

    ENV --> HEADERS
    KEYRING --> HEADERS
    CONFIG --> URL
    HEADERS --> REQUEST[API Request]
    URL --> REQUEST
```

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Jira Integration](../07-integrations/jira-integration.md)
- [Adapter Pattern](./adapter-pattern.md)
