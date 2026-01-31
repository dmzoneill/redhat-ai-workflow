---
name: konflux-status
description: Get overall Konflux build system status
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: konflux_status.yaml
  executable: "true"
---

# konflux_status

Get overall Konflux build system status.

This skill shows:
- Application status
- Running pipelines
- Failed pipelines
- Namespace summary

Uses: konflux_status, konflux_list_applications, konflux_namespace_summary,
      konflux_running_pipelines, konflux_failed_pipelines

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("konflux_status", '{
  "namespace": "aap-aa-tenant",
  "application": "example-application"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load release persona for Konflux status tools**
2. **Check for known Konflux issues**
3. **Get build patterns from knowledge**
4. **Parse build patterns**
5. **Get Konflux overall status**
6. **Parse status**
7. **List applications in namespace**
8. **Parse application list**
9. **Get running pipelines**
10. **Parse running pipelines**
11. **Get failed pipelines**
12. **Parse failed pipelines**
13. **Get namespace summary**
14. **Search for code related to Konflux builds**
15. **Parse Konflux code search results**
16. **Detect failure patterns from Konflux operations**
17. **Learn from Konflux auth failures**
18. **Log skill execution to session**
19. **Track Konflux status checks for patterns**
20. **Update Konflux state in memory**
21. **Track failed pipelines for pattern analysis**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `namespace` | string | No | `aap-aa-tenant` | Konflux namespace |
| `application` | string | No | `-` | Specific application to check (optional) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the konflux_status skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("konflux_status", '{
  "namespace": "aap-aa-tenant",
  "application": "example-application"
}')
```

### Via Command (if configured)

```
/konflux-status
```

## MCP Tools Used

- `code_search`
- `knowledge_query`
- `konflux_failed_pipelines`
- `konflux_list_applications`
- `konflux_namespace_summary`
- `konflux_running_pipelines`
- `konflux_status`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/konflux_status.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/konflux_status.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
