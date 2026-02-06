# Bonfire Tools

> aa_bonfire module for ephemeral environment management

## Diagram

```mermaid
classDiagram
    class BonfireBasic {
        +bonfire_namespace_list(): list
        +bonfire_namespace_describe(ns): dict
        +bonfire_apps_list(ns): list
        +bonfire_config_show(): dict
    }

    class BonfireCore {
        +bonfire_namespace_reserve(duration): dict
        +bonfire_namespace_release(ns): str
        +bonfire_namespace_extend(ns, duration): str
        +bonfire_deploy(ns, app, params): str
    }

    class BonfireExtra {
        +bonfire_deploy_mr(ns, mr_id): str
        +bonfire_process_template(template): str
        +bonfire_get_clowdenv(ns): dict
    }

    BonfireBasic <|-- BonfireCore
    BonfireCore <|-- BonfireExtra
```

## Deployment Flow

```mermaid
sequenceDiagram
    participant User as User
    participant Tool as Bonfire Tool
    participant Bonfire as Bonfire CLI
    participant K8s as Kubernetes
    participant Quay as Quay.io

    User->>Tool: bonfire_namespace_reserve("4h")
    Tool->>Bonfire: bonfire namespace reserve
    Bonfire->>K8s: Create namespace
    K8s-->>Bonfire: Namespace created
    Bonfire-->>Tool: ephemeral-xxxxx

    User->>Tool: bonfire_deploy(ns, app, params)
    Tool->>Bonfire: bonfire deploy
    Bonfire->>Quay: Pull image
    Quay-->>Bonfire: Image pulled
    Bonfire->>K8s: Deploy ClowdApp
    K8s-->>Bonfire: Deployed
    Bonfire-->>Tool: Deployment status

    User->>Tool: bonfire_namespace_release(ns)
    Tool->>Bonfire: bonfire namespace release
    Bonfire->>K8s: Delete namespace
    K8s-->>Bonfire: Deleted
    Bonfire-->>Tool: Released
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_bonfire/src/` | Read operations |
| tools_core.py | `tool_modules/aa_bonfire/src/` | Write operations |
| tools_extra.py | `tool_modules/aa_bonfire/src/` | Advanced operations |

## Tool Summary

| Tool | Tier | Description |
|------|------|-------------|
| `bonfire_namespace_list` | basic | List namespaces |
| `bonfire_namespace_describe` | basic | Describe namespace |
| `bonfire_apps_list` | basic | List deployed apps |
| `bonfire_namespace_reserve` | core | Reserve namespace |
| `bonfire_namespace_release` | core | Release namespace |
| `bonfire_namespace_extend` | core | Extend reservation |
| `bonfire_deploy` | core | Deploy application |
| `bonfire_deploy_mr` | extra | Deploy from MR |

## Environment Variables

```bash
# Required for bonfire commands
export KUBECONFIG=~/.kube/config.e
```

## ClowdApp Deployment

```mermaid
flowchart TB
    subgraph Input[Deployment Input]
        MR[MR ID]
        SHA[Git SHA]
        IMAGE[Image Tag]
    end

    subgraph Build[Image Build]
        QUAY[Quay.io]
        DIGEST[Image Digest]
    end

    subgraph Deploy[Deployment]
        TEMPLATE[ClowdApp Template]
        PARAMS[Parameters]
        CLOWDENV[ClowdEnvironment]
    end

    subgraph Result[Result]
        PODS[Running Pods]
        ROUTES[Routes]
        STATUS[Health Status]
    end

    MR --> SHA
    SHA --> IMAGE
    IMAGE --> QUAY
    QUAY --> DIGEST

    DIGEST --> PARAMS
    TEMPLATE --> PARAMS
    PARAMS --> CLOWDENV

    CLOWDENV --> PODS
    CLOWDENV --> ROUTES
    PODS --> STATUS
```

## Safety Rules

1. **Only release YOUR namespaces** - Check with `bonfire namespace list --mine`
2. **Use full 40-char SHA** - Short SHAs don't exist in Quay
3. **Always use KUBECONFIG env** - Never copy kubeconfig files

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [K8s Tools](./k8s-tools.md)
- [Ephemeral Deployment Flow](../08-data-flows/ephemeral-deployment.md)
