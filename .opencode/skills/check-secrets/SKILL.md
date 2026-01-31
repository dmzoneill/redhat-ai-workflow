---
name: check-secrets
description: Check secrets and configmaps in a namespace
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: check_secrets.yaml
  executable: "true"
---

# check_secrets

Check secrets and configmaps in a namespace.

Useful for:
- Verifying deployment configuration
- Debugging missing env vars
- Auditing secret presence

Uses: kubectl_get_secrets, kubectl_get_configmaps, kubectl_describe_deployment

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("check_secrets", '{
  "namespace": "example-namespace",
  "environment": "stage",
  "deployment": "example-deployment"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load devops persona for Kubernetes tools**
2. **Check for known secrets/k8s issues**
3. **Get security-related gotchas from knowledge**
4. **Parse security-related gotchas**
5. **List secrets in namespace**
6. **Parse secrets list**
7. **List configmaps in namespace**
8. **Parse configmaps list**
9. **Get deployment to check secret/configmap references**
10. **Search for secret usage in code if missing secrets found**
11. **Parse secret code search results**
12. **Check if deployment references existing secrets/configmaps**
13. **Detect failure patterns from secrets check**
14. **Learn from k8s auth failures**
15. **Log skill execution to session**
16. **Track secrets checks for patterns**
17. **Update namespace secrets state**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `namespace` | string | Yes | `-` | Kubernetes namespace |
| `environment` | string | No | `stage` | Environment (stage, production, ephemeral) |
| `deployment` | string | No | `-` | Optional: specific deployment to check references |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the check_secrets skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("check_secrets", '{
  "namespace": "example-namespace",
  "environment": "stage",
  "deployment": "example-deployment"
}')
```

### Via Command (if configured)

```
/check-secrets
```

## MCP Tools Used

- `code_search`
- `knowledge_query`
- `kubectl_describe_deployment`
- `kubectl_get_configmaps`
- `kubectl_get_secrets`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/check_secrets.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/check_secrets.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
