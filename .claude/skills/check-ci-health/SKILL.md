---
name: check-ci-health
description: Diagnose GitLab CI/CD pipeline issues
license: MIT
compatibility: opencode
metadata:
  version: "1.1"
  source: check_ci_health.yaml
  executable: "true"
---

# check_ci_health

Diagnose GitLab CI/CD pipeline issues.

This skill:
- Lists recent pipelines
- Shows failing jobs
- Gets trace logs for failures
- Validates .gitlab-ci.yml

Uses: gitlab_ci_list, gitlab_ci_view, gitlab_ci_trace, gitlab_ci_lint

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("check_ci_health", '{
  "project": "automation-analytics/automation-analytics-backend",
  "status": "failed",
  "limit": 5
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab CI tools**
2. **List recent pipelines**
3. **Parse pipeline list**
4. **Get details of first failed pipeline**
5. **Get trace log of failed pipeline**
6. **Parse trace for error messages**
7. **Lint .gitlab-ci.yml**
8. **Parse lint result**
9. **Find code related to CI failures**
10. **Parse code search results for failures**
11. **Get CI/pipeline gotchas from knowledge**
12. **Parse CI-related gotchas**
13. **Log CI health check to session**
14. **Learn from CI failures for future auto-remediation**
15. **Check for known CI issues**
16. **Save CI health context for other skills**
17. **Detect failure patterns from CI health checks**
18. **Learn from GitLab VPN failures**
19. **Learn from GitLab auth failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `automation-analytics/automation-analytics-backend` | GitLab project path |
| `status` | string | No | `failed` | Filter by status (failed, success, running, all) |
| `limit` | integer | No | `5` | Number of pipelines to show |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the check_ci_health skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("check_ci_health", '{
  "project": "automation-analytics/automation-analytics-backend",
  "status": "failed",
  "limit": 5
}')
```

### Via Command (if configured)

```
/check-ci-health
```

## MCP Tools Used

- `code_search`
- `gitlab_ci_lint`
- `gitlab_ci_list`
- `gitlab_ci_trace`
- `gitlab_ci_view`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/check_ci_health.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/check_ci_health.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
