---
name: deploy-to-ephemeral
description: Deploy application to an ephemeral environment
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: deploy_to_ephemeral.yaml
  executable: "true"
---

# deploy_to_ephemeral

Deploy application to an ephemeral environment.

This skill handles the full deployment workflow:
1. Check available pools and reserve namespace
2. Verify app dependencies
3. Deploy with specified image/parameters
4. Monitor rollout and verify health

Uses: bonfire_pool_list, bonfire_namespace_reserve, bonfire_apps_dependencies,
      bonfire_deploy, kubectl_rollout_status, kubectl_get_pods

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("deploy_to_ephemeral", '{
  "app": "tower-analytics",
  "image_tag": "example-image_tag",
  "duration": "2h",
  "pool": "default",
  "component": "main"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load devops persona for Bonfire and Kubernetes tools**
2. **Check for known deployment issues**
3. **Get deployment gotchas from knowledge**
4. **Parse deployment-related gotchas**
5. **List available namespace pools**
6. **Parse pool availability**
7. **Reserve ephemeral namespace**
8. **Extract namespace name from reservation**
9. **Check app dependencies**
10. **Parse dependency list**
11. **Build image parameter if tag provided**
12. **Deploy application to namespace**
13. **Parse deployment result**
14. **Check deployment rollout status**
15. **Get pod status**
16. **Analyze pod health**
17. **Load recent deployment history for context**
18. **Parse recent deployments for patterns**
19. **Search for deployment-related configuration**
20. **Parse deployment config search results**
21. **Log deployment to session**
22. **Save deployment to history for future reference**
23. **Detect failure patterns from deployment**
24. **Learn from pool exhaustion failures**
25. **Learn from ephemeral cluster auth failures**
26. **Learn from VPN/network failures**
27. **Learn from manifest unknown failures**
28. **Notify team channel about successful ephemeral deployment**
29. **Notify team channel about failed ephemeral deployment**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `app` | string | No | `tower-analytics` | Application name to deploy |
| `image_tag` | string | No | `-` | Image tag (git SHA) to deploy. If empty, uses latest. |
| `duration` | string | No | `2h` | Namespace reservation duration |
| `pool` | string | No | `default` | Namespace pool to use |
| `component` | string | No | `main` | Component to deploy (main or billing) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the deploy_to_ephemeral skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("deploy_to_ephemeral", '{
  "app": "tower-analytics",
  "image_tag": "example-image_tag",
  "duration": "2h",
  "pool": "default",
  "component": "main"
}')
```

### Via Command (if configured)

```
/deploy-to-ephemeral
```

## MCP Tools Used

- `bonfire_apps_dependencies`
- `bonfire_deploy`
- `bonfire_namespace_reserve`
- `bonfire_pool_list`
- `code_search`
- `knowledge_query`
- `kubectl_get_pods`
- `kubectl_rollout_status`
- `learn_tool_fix`
- `memory_append`
- `memory_read`
- `memory_session_log`
- `persona_load`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/deploy_to_ephemeral.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/deploy_to_ephemeral.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
