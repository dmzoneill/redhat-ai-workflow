---
name: environment-overview
description: Get a comprehensive overview of an environment
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: environment_overview.yaml
  executable: "true"
---

# environment_overview

Get a comprehensive overview of an environment.

This skill shows:
- Namespace health
- Service status
- Ingress configuration
- Pod summary

Uses: k8s_environment_summary, k8s_namespace_health, kubectl_get_services,
      kubectl_get_ingress, kubectl_get_pods

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("environment_overview", '{
  "namespace": "example-namespace",
  "environment": "stage"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load devops persona for Kubernetes tools**
2. **Get DevOps gotchas from knowledge**
3. **Parse DevOps gotchas**
4. **Check for known k8s issues**
5. **Get environment summary**
6. **Get namespace health**
7. **Parse namespace health**
8. **List services in namespace**
9. **Parse services**
10. **Get ingress configuration**
11. **Parse ingress**
12. **Get pod summary**
13. **Analyze pod health**
14. **Search for code related to this environment**
15. **Parse environment code search results**
16. **Detect failure patterns from environment overview**
17. **Learn from k8s auth failures**
18. **Log skill execution to session**
19. **Track environment checks for patterns**
20. **Update environment state in memory**
21. **Track unhealthy environments for alerting**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `namespace` | string | Yes | `-` | Kubernetes namespace |
| `environment` | string | No | `stage` | Environment (stage, production, ephemeral) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the environment_overview skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("environment_overview", '{
  "namespace": "example-namespace",
  "environment": "stage"
}')
```

### Via Command (if configured)

```
/environment-overview
```

## MCP Tools Used

- `code_search`
- `k8s_environment_summary`
- `k8s_namespace_health`
- `knowledge_query`
- `kubectl_get_ingress`
- `kubectl_get_pods`
- `kubectl_get_services`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/environment_overview.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/environment_overview.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
