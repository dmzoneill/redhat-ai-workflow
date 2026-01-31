---
name: ci-retry
description: Retry a failed CI pipeline - works with GitLab CI and Konflux/Tekton
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: ci_retry.yaml
  executable: "true"
---

# ci_retry

Retry a failed CI pipeline - works with GitLab CI and Konflux/Tekton.

Detects the CI system and uses appropriate retry mechanism:
- GitLab CI: Uses gitlab_ci_retry
- Konflux/Tekton: Uses tkn_pipeline_start to re-run

Steps:
1. Determine CI system from context (MR, repo, or explicit)
2. Get current pipeline status
3. Retry failed jobs/pipeline
4. Monitor retry status

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("ci_retry", '{
  "mr_id": "example-mr_id",
  "pipeline_id": "example-pipeline_id",
  "tekton_run": "example-tekton_run",
  "project": "automation-analytics/automation-analytics-backend",
  "namespace": "aap-aa-tenant",
  "wait": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab CI tools**
2. **Get CI/pipeline failure patterns from knowledge base**
3. **Parse CI knowledge for context**
4. **Check for known CI issues before retrying**
5. **Load previous retry history**
6. **Check if failing jobs are known to be flaky**
7. **Determine which CI system to use**
8. **Get pipeline for MR**
9. **Extract pipeline ID from MR**
10. **Get GitLab CI pipeline status**
11. **Parse GitLab pipeline status**
12. **Wait for GitLab pipeline to complete**
13. **Load release persona for Tekton tools**
14. **Get Tekton PipelineRun status**
15. **Parse Tekton PipelineRun status**
16. **Get Tekton failure logs**
17. **List recent Tekton runs after retry**
18. **Search for code related to this pipeline**
19. **Parse pipeline code search results**
20. **Log CI retry to session**
21. **Learn from this retry for future reference**
22. **Track jobs that frequently fail then pass on retry**
23. **Save context for other skills to use**
24. **Update MR state if this was an MR retry**
25. **Detect failure patterns from CI retry operations**
26. **Learn from GitLab VPN failures**
27. **Learn from Tekton auth failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mr_id` | integer | No | `-` | GitLab MR ID - will retry its pipeline |
| `pipeline_id` | integer | No | `-` | GitLab CI pipeline ID to retry |
| `tekton_run` | string | No | `-` | Tekton PipelineRun name to re-trigger |
| `project` | string | No | `automation-analytics/automation-analytics-backend` | GitLab project path |
| `namespace` | string | No | `aap-aa-tenant` | Konflux/Tekton namespace |
| `wait` | boolean | No | `false` | Wait for pipeline to complete (up to 15 min) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the ci_retry skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("ci_retry", '{
  "mr_id": "example-mr_id",
  "pipeline_id": "example-pipeline_id",
  "tekton_run": "example-tekton_run",
  "project": "automation-analytics/automation-analytics-backend",
  "namespace": "aap-aa-tenant",
  "wait": false
}')
```

### Via Command (if configured)

```
/ci-retry
```

## MCP Tools Used

- `code_search`
- `gitlab_ci_status`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`
- `tkn_pipelinerun_describe`
- `tkn_pipelinerun_list`
- `tkn_pipelinerun_logs`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/ci_retry.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/ci_retry.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
