# GitLab Integration

> GitLab API integration architecture

## Diagram

```mermaid
graph TB
    subgraph Tools[GitLab Tools]
        BASIC[aa_gitlab_basic<br/>Read operations]
        CORE[aa_gitlab_core<br/>Write operations]
        EXTRA[aa_gitlab_extra<br/>Advanced features]
    end

    subgraph Operations[Operations]
        VIEW_MR[gitlab_view_mr]
        LIST_MRS[gitlab_list_mrs]
        CREATE_MR[gitlab_create_mr]
        MERGE[gitlab_merge_mr]
        PIPELINES[gitlab_pipelines]
        APPROVE[gitlab_approve_mr]
    end

    subgraph API[GitLab API]
        REST[REST API v4]
        AUTH[Personal Access Token]
    end

    subgraph Config[Configuration]
        URL[gitlab_url]
        TOKEN[gitlab_token]
        PROJECT[project_id]
    end

    Tools --> Operations
    Operations --> REST
    REST --> AUTH
    Config --> AUTH
```

## API Flow

```mermaid
sequenceDiagram
    participant Tool as GitLab Tool
    participant Client as HTTP Client
    participant Auth as Auth Handler
    participant API as GitLab API

    Tool->>Client: Make request
    Client->>Auth: Get credentials
    Auth-->>Client: Personal access token

    Client->>API: GET/POST /api/v4/...
    Note over Client,API: PRIVATE-TOKEN: {token}

    API-->>Client: JSON response
    Client-->>Tool: Parsed data
```

## Tool Tiers

### Basic (Read-only)

| Tool | Description | Endpoint |
|------|-------------|----------|
| gitlab_view_mr | View MR details | GET /projects/{id}/merge_requests/{iid} |
| gitlab_list_mrs | List MRs | GET /projects/{id}/merge_requests |
| gitlab_pipelines | List pipelines | GET /projects/{id}/pipelines |
| gitlab_get_diff | Get MR diff | GET /projects/{id}/merge_requests/{iid}/changes |

### Core (Write)

| Tool | Description | Endpoint |
|------|-------------|----------|
| gitlab_create_mr | Create MR | POST /projects/{id}/merge_requests |
| gitlab_merge_mr | Merge MR | PUT /projects/{id}/merge_requests/{iid}/merge |
| gitlab_approve_mr | Approve MR | POST /projects/{id}/merge_requests/{iid}/approve |
| gitlab_add_comment | Add comment | POST /projects/{id}/merge_requests/{iid}/notes |

### Extra (Advanced)

| Tool | Description | Endpoint |
|------|-------------|----------|
| gitlab_rebase_mr | Rebase MR | PUT /projects/{id}/merge_requests/{iid}/rebase |
| gitlab_cancel_pipeline | Cancel pipeline | POST /projects/{id}/pipelines/{id}/cancel |
| gitlab_retry_pipeline | Retry pipeline | POST /projects/{id}/pipelines/{id}/retry |

## MR Workflow

```mermaid
flowchart TB
    subgraph Create[Create MR]
        BRANCH[Create branch]
        COMMIT[Push commits]
        CREATE_MR[gitlab_create_mr]
    end

    subgraph Review[Review]
        VIEW[gitlab_view_mr]
        DIFF[gitlab_get_diff]
        COMMENT[gitlab_add_comment]
        APPROVE[gitlab_approve_mr]
    end

    subgraph Merge[Merge]
        CHECK_PIPELINE[Check pipeline]
        MERGE_MR[gitlab_merge_mr]
    end

    Create --> Review
    Review --> Merge
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic | `tool_modules/aa_gitlab/src/tools_basic.py` | Read tools |
| tools_core | `tool_modules/aa_gitlab/src/tools_core.py` | Write tools |
| tools_extra | `tool_modules/aa_gitlab/src/tools_extra.py` | Advanced tools |
| adapter | `tool_modules/aa_gitlab/src/adapter.py` | Memory adapter |

## Related Diagrams

- [Tool Tiers](../03-tools/tool-tiers.md)
- [GitLab Tools](../03-tools/gitlab-tools.md)
- [Auth Flows](./auth-flows.md)
