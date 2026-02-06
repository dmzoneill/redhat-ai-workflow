# Konflux Integration

> Konflux release pipeline integration

## Diagram

```mermaid
graph TB
    subgraph Tools[Konflux Tools]
        BASIC[aa_konflux_basic<br/>Read operations]
        CORE[aa_konflux_core<br/>Write operations]
        EXTRA[aa_konflux_extra<br/>Advanced features]
    end

    subgraph Operations[Operations]
        APPS[konflux_list_apps]
        COMPONENTS[konflux_list_components]
        SNAPSHOTS[konflux_list_snapshots]
        RELEASES[konflux_list_releases]
        CREATE_REL[konflux_create_release]
    end

    subgraph API[Konflux API]
        K8S_API[Kubernetes CRDs]
        TENANT[Tenant Namespace]
    end

    Tools --> Operations
    Operations --> K8S_API
    K8S_API --> TENANT
```

## Release Pipeline

```mermaid
flowchart LR
    subgraph Build[Build Phase]
        COMMIT[Git Commit]
        BUILD[Build Image]
        PUSH[Push to Quay]
    end

    subgraph Snapshot[Snapshot Phase]
        CREATE_SNAP[Create Snapshot]
        TEST[Run Tests]
        APPROVE[Approve Snapshot]
    end

    subgraph Release[Release Phase]
        CREATE_REL[Create Release]
        PROMOTE[Promote to Env]
        VERIFY[Verify Deployment]
    end

    Build --> Snapshot
    Snapshot --> Release
```

## Tool Tiers

### Basic (Read-only)

| Tool | Description | Resource |
|------|-------------|----------|
| konflux_list_apps | List applications | Application CRD |
| konflux_list_components | List components | Component CRD |
| konflux_list_snapshots | List snapshots | Snapshot CRD |
| konflux_list_releases | List releases | Release CRD |
| konflux_get_release | Get release details | Release CRD |

### Core (Write)

| Tool | Description | Resource |
|------|-------------|----------|
| konflux_create_release | Create release | Release CRD |
| konflux_approve_snapshot | Approve snapshot | Snapshot CRD |

### Extra (Advanced)

| Tool | Description | Resource |
|------|-------------|----------|
| konflux_rollback | Rollback release | Release CRD |
| konflux_promote | Promote to env | ReleasePlan CRD |

## Release Flow

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant Tool as konflux_create_release
    participant K8s as Konflux API
    participant Quay as Quay.io
    participant Target as Target Env

    User->>Tool: Create release
    Tool->>K8s: Get latest snapshot
    K8s-->>Tool: Snapshot with image refs

    Tool->>K8s: Create Release CR
    K8s->>Quay: Pull image
    K8s->>Target: Deploy to environment

    K8s-->>Tool: Release status
    Tool-->>User: Release created
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic | `tool_modules/aa_konflux/src/tools_basic.py` | Read tools |
| tools_core | `tool_modules/aa_konflux/src/tools_core.py` | Write tools |
| tools_extra | `tool_modules/aa_konflux/src/tools_extra.py` | Advanced tools |

## Related Diagrams

- [Konflux Tools](../03-tools/konflux-tools.md)
- [Deployment Skills](../04-skills/deployment-skills.md)
- [Release Persona](../05-personas/persona-definitions.md)
