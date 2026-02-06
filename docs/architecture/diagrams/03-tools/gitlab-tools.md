# GitLab Tools

> aa_gitlab module for GitLab API integration

## Diagram

```mermaid
classDiagram
    class GitLabBasic {
        +gitlab_view_mr(mr_id): dict
        +gitlab_list_mrs(state): list
        +gitlab_get_pipeline(id): dict
        +gitlab_list_pipelines(): list
        +gitlab_get_diff(mr_id): str
        +gitlab_search_code(query): list
    }

    class GitLabCore {
        +gitlab_create_mr(source, target, title): dict
        +gitlab_update_mr(mr_id, fields): dict
        +gitlab_approve_mr(mr_id): dict
        +gitlab_add_comment(mr_id, comment): dict
        +gitlab_retry_pipeline(id): dict
        +gitlab_cancel_pipeline(id): dict
    }

    class GitLabExtra {
        +gitlab_merge_mr(mr_id): dict
        +gitlab_rebase_mr(mr_id): dict
        +gitlab_cherry_pick(sha, branch): dict
        +gitlab_create_branch(name, ref): dict
        +gitlab_delete_branch(name): dict
        +gitlab_compare_branches(from, to): dict
    }

    class GitLabAdapter {
        +query(question): list
        +get_mr(id): dict
        +search_mrs(query): list
    }

    GitLabBasic <|-- GitLabCore
    GitLabCore <|-- GitLabExtra
    GitLabAdapter --> GitLabBasic : uses
```

## API Flow

```mermaid
sequenceDiagram
    participant Tool as GitLab Tool
    participant Client as HTTP Client
    participant GitLab as GitLab API
    participant Project as Project Config

    Tool->>Project: Get project ID
    Project-->>Tool: Project ID

    Tool->>Client: Build request
    Note over Client: Add PRIVATE-TOKEN header
    Client->>GitLab: REST API call
    GitLab-->>Client: JSON response
    Client-->>Tool: Parsed response

    Tool-->>Tool: Format for Claude
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_gitlab/src/` | Read operations |
| tools_core.py | `tool_modules/aa_gitlab/src/` | Write operations |
| tools_extra.py | `tool_modules/aa_gitlab/src/` | Advanced operations |
| adapter.py | `tool_modules/aa_gitlab/src/` | Memory adapter |
| server.py | `tool_modules/aa_gitlab/src/` | Standalone server |

## Tool Summary

| Tool | Tier | Description |
|------|------|-------------|
| `gitlab_view_mr` | basic | View MR details |
| `gitlab_list_mrs` | basic | List merge requests |
| `gitlab_get_pipeline` | basic | Get pipeline status |
| `gitlab_get_diff` | basic | Get MR diff |
| `gitlab_create_mr` | core | Create merge request |
| `gitlab_approve_mr` | core | Approve MR |
| `gitlab_retry_pipeline` | core | Retry failed pipeline |
| `gitlab_merge_mr` | extra | Merge MR |
| `gitlab_rebase_mr` | extra | Rebase MR |

## Configuration

```json
{
  "gitlab": {
    "url": "https://gitlab.cee.redhat.com",
    "project": "automation-analytics/automation-analytics-backend",
    "token_env": "GITLAB_TOKEN"
  }
}
```

## MR Workflow

```mermaid
flowchart TB
    subgraph Create[Create MR]
        BRANCH[Create branch]
        PUSH[Push commits]
        CREATE_MR[gitlab_create_mr]
    end

    subgraph Review[Review]
        VIEW[gitlab_view_mr]
        DIFF[gitlab_get_diff]
        COMMENT[gitlab_add_comment]
        APPROVE[gitlab_approve_mr]
    end

    subgraph Merge[Merge]
        PIPELINE[gitlab_get_pipeline]
        REBASE[gitlab_rebase_mr]
        MERGE[gitlab_merge_mr]
    end

    BRANCH --> PUSH
    PUSH --> CREATE_MR
    CREATE_MR --> VIEW
    VIEW --> DIFF
    DIFF --> COMMENT
    COMMENT --> APPROVE
    APPROVE --> PIPELINE
    PIPELINE --> REBASE
    REBASE --> MERGE
```

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [GitLab Integration](../07-integrations/gitlab-integration.md)
- [Git Tools](./git-tools.md)
