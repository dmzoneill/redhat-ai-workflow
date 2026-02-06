# Kubernetes Tools

> aa_k8s module for Kubernetes cluster operations

## Diagram

```mermaid
classDiagram
    class K8sBasic {
        +k8s_get_pods(namespace): list
        +k8s_get_deployments(namespace): list
        +k8s_describe(resource, name, ns): str
        +k8s_logs(pod, namespace, tail): str
        +k8s_get_events(namespace): list
        +k8s_get_configmap(name, ns): dict
    }

    class K8sCore {
        +k8s_apply(manifest): str
        +k8s_delete(resource, name, ns): str
        +k8s_scale(deployment, replicas, ns): str
        +k8s_rollout_restart(deployment, ns): str
        +k8s_set_env(deployment, key, value, ns): str
        +k8s_patch(resource, name, patch, ns): str
    }

    class K8sExtra {
        +k8s_port_forward(pod, ports, ns): str
        +k8s_exec(pod, command, ns): str
        +k8s_cp(src, dest, ns): str
        +k8s_top_pods(namespace): list
        +k8s_get_secret(name, ns): dict
        +k8s_rollout_status(deployment, ns): str
    }

    K8sBasic <|-- K8sCore
    K8sCore <|-- K8sExtra
```

## Multi-Cluster Access

```mermaid
flowchart TB
    subgraph Configs[Kubeconfig Files]
        STAGE[~/.kube/config.s<br/>Stage]
        PROD[~/.kube/config.p<br/>Production]
        EPHEMERAL[~/.kube/config.e<br/>Ephemeral]
        KONFLUX[~/.kube/config.k<br/>Konflux]
    end

    subgraph Tools[K8s Tools]
        TOOL[k8s_* tools]
        CLUSTER[cluster parameter]
    end

    subgraph Commands[kubectl/oc]
        KUBECTL[kubectl --kubeconfig]
        OC[oc --kubeconfig]
    end

    TOOL --> CLUSTER
    CLUSTER --> STAGE
    CLUSTER --> PROD
    CLUSTER --> EPHEMERAL
    CLUSTER --> KONFLUX

    STAGE --> KUBECTL
    PROD --> KUBECTL
    EPHEMERAL --> OC
    KONFLUX --> OC
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_k8s/src/` | Read operations |
| tools_core.py | `tool_modules/aa_k8s/src/` | Write operations |
| tools_extra.py | `tool_modules/aa_k8s/src/` | Advanced operations |
| server.py | `tool_modules/aa_k8s/src/` | Standalone server |

## Tool Summary

| Tool | Tier | Description |
|------|------|-------------|
| `k8s_get_pods` | basic | List pods |
| `k8s_describe` | basic | Describe resource |
| `k8s_logs` | basic | Get pod logs |
| `k8s_get_events` | basic | Get events |
| `k8s_apply` | core | Apply manifest |
| `k8s_delete` | core | Delete resource |
| `k8s_scale` | core | Scale deployment |
| `k8s_rollout_restart` | core | Restart deployment |
| `k8s_port_forward` | extra | Port forwarding |
| `k8s_exec` | extra | Execute in pod |

## Cluster Parameter

| Value | Kubeconfig | Environment |
|-------|------------|-------------|
| `stage` | `~/.kube/config.s` | Stage |
| `prod` | `~/.kube/config.p` | Production |
| `ephemeral` | `~/.kube/config.e` | Ephemeral |
| `konflux` | `~/.kube/config.k` | Konflux |

## Auto-Heal Integration

```mermaid
flowchart TB
    TOOL[K8s Tool] --> CALL[API Call]
    CALL --> CHECK{Auth OK?}
    
    CHECK -->|Yes| SUCCESS[Return Result]
    CHECK -->|No| DETECT[Detect Auth Error]
    
    DETECT --> HEAL[Auto-Heal]
    HEAL --> LOGIN[kube_login]
    LOGIN --> RETRY[Retry Call]
    RETRY --> SUCCESS
```

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Kubernetes Integration](../07-integrations/kubernetes-integration.md)
- [Bonfire Tools](./bonfire-tools.md)
- [Auto-Heal Decorator](../01-server/auto-heal-decorator.md)
