# ☸️ k8s

> Kubernetes operations

## Overview

The `aa-k8s` module provides tools for Kubernetes operations including pod management, logs, events, and deployments.

## Tool Count

**26 tools**

## Tools

### Pods

| Tool | Description |
|------|-------------|
| `kubectl_get_pods` | List pods |
| `kubectl_describe_pod` | Describe pod |
| `kubectl_logs` | Get pod logs |
| `kubectl_delete_pod` | Delete pod |
| `kubectl_exec` | Execute command in pod |

### Deployments

| Tool | Description |
|------|-------------|
| `kubectl_get_deployments` | List deployments |
| `kubectl_describe_deployment` | Describe deployment |
| `kubectl_rollout_status` | Check rollout status |
| `kubectl_rollout_restart` | Rolling restart |
| `kubectl_scale` | Scale replicas |

### Networking

| Tool | Description |
|------|-------------|
| `kubectl_get_services` | List services |
| `kubectl_get_ingress` | List ingress |

### Config

| Tool | Description |
|------|-------------|
| `kubectl_get_configmaps` | List configmaps |
| `kubectl_get_secrets` | List secrets |

### Debugging

| Tool | Description |
|------|-------------|
| `kubectl_get_events` | Get events |
| `kubectl_top_pods` | Resource usage |
| `kubectl_get` | Get any resource |

## Kubeconfig

The module uses different kubeconfig files for different environments:

| Environment | Kubeconfig |
|-------------|------------|
| Stage | `~/.kube/config.s` |
| Production | `~/.kube/config.p` |
| Ephemeral | `~/.kube/config.e` |

## Usage Examples

### List Pods

```python
kubectl_get_pods(
    namespace="tower-analytics-stage",
    environment="stage"
)
```

### Get Logs

```python
kubectl_logs(
    pod="analytics-api-xxx",
    namespace="tower-analytics-prod",
    environment="production",
    tail=100
)
```

### Check Events

```python
kubectl_get_events(
    namespace="ephemeral-nx6n2s",
    environment="ephemeral"
)
```

## Loaded By

- [🔧 DevOps Agent](../agents/devops.md)
- [🚨 Incident Agent](../agents/incident.md)

## Related Skills

- [test_mr_ephemeral](../skills/test_mr_ephemeral.md) - Uses for pod checks
- [investigate_alert](../skills/investigate_alert.md) - Pod status checks
- [debug_prod](../skills/debug_prod.md) - Deep debugging

