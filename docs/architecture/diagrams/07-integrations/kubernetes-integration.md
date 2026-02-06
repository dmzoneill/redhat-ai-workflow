# Kubernetes Integration

> Multi-cluster Kubernetes API integration

## Diagram

```mermaid
graph TB
    subgraph Tools[K8s Tools]
        BASIC[aa_k8s_basic<br/>Read operations]
        CORE[aa_k8s_core<br/>Write operations]
        EXTRA[aa_k8s_extra<br/>Advanced features]
    end

    subgraph Operations[Operations]
        GET[k8s_get]
        DESCRIBE[k8s_describe]
        LOGS[k8s_logs]
        APPLY[k8s_apply]
        DELETE[k8s_delete]
        EXEC[k8s_exec]
    end

    subgraph Clusters[Clusters]
        EPHEMERAL[Ephemeral<br/>~/.kube/config.e]
        STAGE[Stage<br/>~/.kube/config.s]
        PROD[Production<br/>~/.kube/config.p]
    end

    subgraph API[Kubernetes API]
        KUBECTL[kubectl / oc]
        REST[REST API]
    end

    Tools --> Operations
    Operations --> KUBECTL
    KUBECTL --> Clusters
```

## Multi-Cluster Access

```mermaid
flowchart TB
    subgraph Kubeconfigs[Kubeconfig Files]
        CONFIG_E["~/.kube/config.e<br/>Ephemeral"]
        CONFIG_S["~/.kube/config.s<br/>Stage"]
        CONFIG_P["~/.kube/config.p<br/>Production"]
    end

    subgraph Tool[Tool Execution]
        SELECT[Select cluster]
        SET_ENV["KUBECONFIG=config.{env}"]
        EXECUTE[Execute kubectl]
    end

    subgraph Safety[Safety Rules]
        NEVER_COPY["NEVER copy kubeconfig!"]
        USE_FLAG["Use --kubeconfig flag"]
    end

    Kubeconfigs --> SELECT
    SELECT --> SET_ENV
    SET_ENV --> EXECUTE
    Safety -.->|Enforce| Tool
```

## Tool Tiers

### Basic (Read-only)

| Tool | Description | Command |
|------|-------------|---------|
| k8s_get | Get resources | kubectl get {resource} |
| k8s_describe | Describe resource | kubectl describe {resource} |
| k8s_logs | Get pod logs | kubectl logs {pod} |
| k8s_get_events | Get events | kubectl get events |

### Core (Write)

| Tool | Description | Command |
|------|-------------|---------|
| k8s_apply | Apply manifest | kubectl apply -f |
| k8s_delete | Delete resource | kubectl delete {resource} |
| k8s_scale | Scale deployment | kubectl scale --replicas |
| k8s_rollout | Manage rollouts | kubectl rollout |

### Extra (Advanced)

| Tool | Description | Command |
|------|-------------|---------|
| k8s_exec | Execute in pod | kubectl exec |
| k8s_port_forward | Port forward | kubectl port-forward |
| k8s_cp | Copy files | kubectl cp |

## Auto-Heal Integration

```mermaid
sequenceDiagram
    participant Tool as k8s_get_pods
    participant AutoHeal as Auto-Heal Decorator
    participant Login as kube_login
    participant K8s as Kubernetes API

    Tool->>K8s: Get pods
    K8s-->>Tool: 401 Unauthorized

    Tool->>AutoHeal: Detect auth failure
    AutoHeal->>Login: Execute kube_login
    Login-->>AutoHeal: Token refreshed

    AutoHeal->>K8s: Retry: Get pods
    K8s-->>AutoHeal: Pod list
    AutoHeal-->>Tool: Success
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic | `tool_modules/aa_k8s/src/tools_basic.py` | Read tools |
| tools_core | `tool_modules/aa_k8s/src/tools_core.py` | Write tools |
| tools_extra | `tool_modules/aa_k8s/src/tools_extra.py` | Advanced tools |

## Related Diagrams

- [K8s Tools](../03-tools/k8s-tools.md)
- [Auto-Heal Decorator](../01-server/auto-heal-decorator.md)
- [Bonfire Tools](../03-tools/bonfire-tools.md)
