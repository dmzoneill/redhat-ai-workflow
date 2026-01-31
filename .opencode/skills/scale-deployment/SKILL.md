---
name: scale-deployment
description: Scale a Kubernetes deployment and monitor the rollout
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: scale_deployment.yaml
  executable: "true"
---

# scale_deployment

Scale a Kubernetes deployment and monitor the rollout.

Use for:
- Scaling up for high traffic
- Scaling down to save resources
- Testing with different replica counts
- Recovering from OOM by increasing replicas

The skill will:
1. Get current deployment state
2. Scale to desired replicas
3. Monitor rollout progress
4. Report final state

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("scale_deployment", '{
  "deployment": "example-deployment",
  "replicas": "example-replicas",
  "namespace": "tower-analytics-stage",
  "environment": "stage",
  "wait": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load devops persona for Kubernetes tools**
2. **Check for known scaling issues**
3. **Get scaling-related gotchas from knowledge**
4. **Parse scaling-related gotchas**
5. **Load previous scaling history for this deployment**
6. **Get current deployment info**
7. **Parse current deployment state**
8. **Scale the deployment to desired replicas**
9. **Parse scale result**
10. **Check rollout status**
11. **Parse rollout status**
12. **Get final deployment state**
13. **Get pod status after scaling**
14. **Parse final state**
15. **Log scaling action**
16. **Learn from this scaling for future reference**
17. **Track scaling failures for auto-remediation**
18. **Update environment state after scaling**
19. **Search for code related to this deployment**
20. **Parse deployment code search results**
21. **Detect failure patterns from scale operations**
22. **Learn from k8s auth failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `deployment` | string | Yes | `-` | Deployment name to scale |
| `replicas` | integer | Yes | `-` | Desired number of replicas |
| `namespace` | string | No | `tower-analytics-stage` | Kubernetes namespace |
| `environment` | string | No | `stage` | Environment: 'stage', 'production', 'ephemeral' |
| `wait` | boolean | No | `true` | Wait for rollout to complete |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the scale_deployment skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("scale_deployment", '{
  "deployment": "example-deployment",
  "replicas": "example-replicas",
  "namespace": "tower-analytics-stage",
  "environment": "stage",
  "wait": true
}')
```

### Via Command (if configured)

```
/scale-deployment
```

## MCP Tools Used

- `code_search`
- `knowledge_query`
- `kubectl_get_deployments`
- `kubectl_get_pods`
- `kubectl_rollout`
- `kubectl_scale`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/scale_deployment.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/scale_deployment.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
