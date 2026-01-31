---
name: appinterface-check
description: Comprehensive app-interface validation and release readiness check
license: MIT
compatibility: opencode
metadata:
  version: "3.1"
  source: appinterface_check.yaml
  executable: "true"
---

# appinterface_check

Comprehensive app-interface validation and release readiness check.

This skill:
- Validates YAML configuration, $ref paths, and SHA formats
- Compares app-interface refs to live cluster state
- Shows resource quotas and limits
- Lists pending MRs that may affect release
- Assesses overall release readiness with blockers/warnings

Uses: appinterface_get_saas, appinterface_diff, appinterface_resources,
      kubectl_get_deployments, kubectl_get_resourcequotas, gitlab_mr_list

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("appinterface_check", '{
  "saas_file": "tower-analytics",
  "namespace_stage": "tower-analytics-stage",
  "namespace_prod": "tower-analytics-prod",
  "deployment": "automation-analytics-api-fastapi-v2",
  "stale_days": 7,
  "gitlab_project": "automation-analytics/automation-analytics-backend"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load release persona for app-interface tools**
2. **Check for known app-interface and release issues**
3. **Get release-related gotchas from knowledge**
4. **Parse release-related gotchas**
5. **Get SaaS file details**
6. **Extract stage and prod refs from SaaS file**
7. **Validate $ref paths and SHA formats**
8. **Load devops persona for Kubernetes tools**
9. **Get live deployment from stage cluster**
10. **Extract deployed image SHA from stage**
11. **Get live deployment from prod cluster**
12. **Extract deployed image SHA from prod**
13. **Compare app-interface refs to live state**
14. **Get diff from main branch**
15. **Parse diff for tower-analytics changes**
16. **List app-interface resources**
17. **Parse resources**
18. **Get resource quotas from stage namespace**
19. **Get limit ranges from stage namespace**
20. **Parse quota and limit information**
21. **Load developer persona for GitLab tools**
22. **Get open MRs that might affect this service**
23. **Search for release-related code and configuration**
24. **Parse release code search results**
25. **Parse pending MRs for release-relevant changes**
26. **Assess overall release readiness**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `saas_file` | string | No | `tower-analytics` | SaaS file name to check (service name) |
| `namespace_stage` | string | No | `tower-analytics-stage` | Stage namespace |
| `namespace_prod` | string | No | `tower-analytics-prod` | Production namespace |
| `deployment` | string | No | `automation-analytics-api-fastapi-v2` | Deployment to check for live SHA |
| `stale_days` | integer | No | `7` | Alert if deployed SHA is older than this many days |
| `gitlab_project` | string | No | `automation-analytics/automation-analytics-backend` | GitLab project to check for pending MRs |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the appinterface_check skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("appinterface_check", '{
  "saas_file": "tower-analytics",
  "namespace_stage": "tower-analytics-stage",
  "namespace_prod": "tower-analytics-prod",
  "deployment": "automation-analytics-api-fastapi-v2",
  "stale_days": 7,
  "gitlab_project": "automation-analytics/automation-analytics-backend"
}')
```

### Via Command (if configured)

```
/appinterface-check
```

## MCP Tools Used

- `appinterface_diff`
- `appinterface_get_saas`
- `appinterface_resources`
- `code_search`
- `gitlab_mr_list`
- `knowledge_query`
- `kubectl_get`
- `kubectl_get_deployments`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/appinterface_check.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/appinterface_check.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
