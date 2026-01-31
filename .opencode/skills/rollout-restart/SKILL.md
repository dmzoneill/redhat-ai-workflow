---
name: rollout-restart
description: Restart a Kubernetes deployment and monitor its rollout
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: rollout_restart.yaml
  executable: "true"
---

# rollout_restart

Restart a Kubernetes deployment and monitor its rollout.

This is useful for:
- Picking up new ConfigMap/Secret changes
- Recovering from stuck pods
- Forcing a fresh start without redeploying

Uses: kubectl_rollout_restart, kubectl_rollout_status, kubectl_describe_deployment,
      kubectl_get_pods

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("rollout_restart", '{
  "deployment": "example-deployment",
  "namespace": "example-namespace",
  "environment": "stage",
  "wait": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load devops persona for Kubernetes tools**
2. **Check for known k8s rollout issues**
3. **Get rollout-related gotchas from knowledge**
4. **Parse rollout-related gotchas**
5. **Load previous restart history for this deployment**
6. **Get deployment state before restart**
7. **Parse current deployment state**
8. **Trigger rolling restart**
9. **Parse restart result**
10. **Monitor rollout progress**
11. **Parse rollout status**
12. **Get pod status after restart**
13. **Analyze pod health after restart**
14. **Log restart to session**
15. **Learn from this restart for future reference**
16. **Track deployments that frequently have issues**
17. **Update environment state after restart**
18. **Search for code related to this deployment**
19. **Parse deployment code search results**
20. **Detect failure patterns from rollout restart**
21. **Learn from k8s auth failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `deployment` | string | Yes | `-` | Deployment name to restart |
| `namespace` | string | Yes | `-` | Kubernetes namespace |
| `environment` | string | No | `stage` | Environment (stage, production, ephemeral) |
| `wait` | boolean | No | `true` | Wait for rollout to complete |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the rollout_restart skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("rollout_restart", '{
  "deployment": "example-deployment",
  "namespace": "example-namespace",
  "environment": "stage",
  "wait": true
}')
```

### Via Command (if configured)

```
/rollout-restart
```

## MCP Tools Used

- `code_search`
- `knowledge_query`
- `kubectl_describe_deployment`
- `kubectl_get_pods`
- `kubectl_rollout_restart`
- `kubectl_rollout_status`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/rollout_restart.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/rollout_restart.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
