# 🔧 DevOps Agent

> Infrastructure, deployments, and Kubernetes operations

## Overview

The DevOps agent is focused on infrastructure operations, particularly ephemeral environment deployment and Kubernetes management.

## Quick Load

```
Load the devops agent
```

## Tools Loaded

| Module | Tools | Description |
|--------|-------|-------------|
| [k8s](../mcp-servers/k8s.md) | 26 | Kubernetes operations |
| [bonfire](../mcp-servers/bonfire.md) | 21 | Ephemeral namespaces |
| [quay](../mcp-servers/quay.md) | 8 | Container images |
| [gitlab](../mcp-servers/gitlab.md) | 35 | MR details for deploy |

**Total:** ~90 tools

## Skills Available

| Skill | Description |
|-------|-------------|
| [🧪 test_mr_ephemeral](../skills/test_mr_ephemeral.md) | Deploy MR to ephemeral environment |
| [🚨 investigate_alert](../skills/investigate_alert.md) | Quick alert triage |
| [🐛 debug_prod](../skills/debug_prod.md) | Deep production debugging |

## Use Cases

### Deploy MR to Ephemeral

```
You: Deploy MR 1450 to ephemeral

Claude: 🧪 Deploying MR !1450...

        ✅ Commit: 1244ec49e602...
        ✅ Image found in Quay
        ✅ Reserved: ephemeral-nx6n2s
        ✅ Deployed tower-analytics-clowdapp
        ⏳ Waiting for pods... (3/3 ready)

        Namespace ready for testing!
```

### Check Your Namespaces

```
You: List my ephemeral namespaces

Claude: 📦 Your Ephemeral Namespaces:

        | Namespace | Status | Expires |
        |-----------|--------|---------|
        | ephemeral-nx6n2s | Ready | 1h 45m |
        | ephemeral-abc123 | Ready | 30m |
```

### Debug Pod Issues

```
You: Check pods in ephemeral-nx6n2s

Claude: ☸️ Pods in ephemeral-nx6n2s:

        | Pod | Status | Restarts |
        |-----|--------|----------|
        | analytics-api-xxx | Running ✅ | 0 |
        | analytics-worker-xxx | Running ✅ | 0 |
```

## Key Commands

### Namespace Management

```
bonfire_namespace_list       # List your namespaces
bonfire_namespace_reserve    # Reserve a new namespace
bonfire_namespace_release    # Release a namespace
```

### Deployment

```
bonfire_deploy_aa            # Deploy main ClowdApp
quay_get_tag                 # Check image exists
```

### Kubernetes

```
kubectl_get_pods             # List pods
kubectl_logs                 # Get container logs
kubectl_describe_pod         # Pod details
kubectl_get_events           # K8s events
```

## Critical Rules

⚠️ **Never do these:**

| ❌ Don't | ✅ Do Instead |
|---------|---------------|
| `cp ~/.kube/config.e ~/.kube/config` | Use MCP tools or `--kubeconfig` flag |
| Use short SHA (8 chars) | Always use full 40-char SHA |
| Run raw `bonfire deploy` | Use `bonfire_deploy_aa` MCP tool |

## When to Switch Agents

Switch to **Developer** agent when you need to:
- Create or review MRs
- Work on Jira issues
- Do code-level work

Switch to **Incident** agent when you need to:
- Search logs in Kibana
- Query Prometheus metrics
- Manage alert silences

## Related

- [👨‍💻 Developer Agent](./developer.md)
- [🚨 Incident Agent](./incident.md)
- [test_mr_ephemeral Skill](../skills/test_mr_ephemeral.md)
