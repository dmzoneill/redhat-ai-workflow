---
name: cancel-pipeline
description: Cancel a running or stuck Tekton pipeline
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: cancel_pipeline.yaml
  executable: "true"
---

# cancel_pipeline

Cancel a running or stuck Tekton pipeline.

Use when:
- A pipeline is stuck and needs to be killed
- You started a wrong build
- Need to free up cluster resources
- Want to retry with different parameters

The skill will:
1. List running pipelines
2. Get pipeline status
3. Cancel the specified pipeline
4. Optionally delete the run
5. Show how to retry

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("cancel_pipeline", '{
  "run_name": "example-run_name",
  "namespace": "aap-aa-tenant",
  "delete": false,
  "list_only": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load release persona for Tekton pipeline tools**
2. **Get pipeline patterns and gotchas from knowledge base**
3. **Parse pipeline knowledge for cancel context**
4. **Check for known Konflux issues before starting**
5. **List recent pipeline runs**
6. **Parse pipeline runs**
7. **Select pipeline to cancel**
8. **Get details of the target run**
9. **List task runs for this pipeline**
10. **Parse run details**
11. **Cancel the pipeline run**
12. **Parse cancel result**
13. **Delete the pipeline run**
14. **Parse delete result**
15. **Log cancel action**
16. **Track pipeline cancellations for patterns**
17. **Track pipelines that frequently get stuck**
18. **Search for pipeline-related code**
19. **Parse pipeline code search results**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `run_name` | string | No | `-` | PipelineRun name to cancel (lists running if not specified) |
| `namespace` | string | No | `aap-aa-tenant` | Konflux/Tekton namespace |
| `delete` | boolean | No | `false` | Delete the PipelineRun after cancelling |
| `list_only` | boolean | No | `false` | Just list running pipelines without cancelling |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the cancel_pipeline skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("cancel_pipeline", '{
  "run_name": "example-run_name",
  "namespace": "aap-aa-tenant",
  "delete": false,
  "list_only": false
}')
```

### Via Command (if configured)

```
/cancel-pipeline
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `knowledge_query`
- `memory_session_log`
- `persona_load`
- `tkn_pipelinerun_cancel`
- `tkn_pipelinerun_delete`
- `tkn_pipelinerun_describe`
- `tkn_pipelinerun_list`
- `tkn_taskrun_list`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/cancel_pipeline.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/cancel_pipeline.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
