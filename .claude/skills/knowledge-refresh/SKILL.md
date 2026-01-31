---
name: knowledge-refresh
description: Refresh project knowledge and vector index
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: knowledge_refresh.yaml
  executable: "true"
---

# knowledge_refresh

Refresh project knowledge and vector index.

Use this skill to:
- Update the vector index with recent code changes
- Re-scan project for architecture changes
- Refresh knowledge confidence scores
- Start/restart file watchers

Run this periodically or after major code changes.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("knowledge_refresh", '{
  "project": "example-project",
  "full_rescan": false,
  "restart_watcher": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Check for known vector indexing issues before starting**
2. **detect_project**
3. **set_project**
4. **Get current vector index stats**
5. **Parse current stats**
6. **Update vector index with recent changes**
7. **Parse index update result**
8. **Restart file watcher for automatic updates**
9. **Parse watcher result**
10. **Perform full knowledge rescan**
11. **Get updated vector index stats**
12. **Parse updated stats**
13. **build_summary**
14. **Detect failure patterns from knowledge refresh**
15. **Learn from permission failures**
16. **Log refresh to session**
17. **Track knowledge refreshes for patterns**
18. **Update project knowledge state in memory**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `-` | Project name from config.json (auto-detected from cwd if empty) |
| `full_rescan` | boolean | No | `false` | If true, perform full rescan instead of incremental update |
| `restart_watcher` | boolean | No | `true` | If true, restart the file watcher |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the knowledge_refresh skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("knowledge_refresh", '{
  "project": "example-project",
  "full_rescan": false,
  "restart_watcher": true
}')
```

### Via Command (if configured)

```
/knowledge-refresh
```

## MCP Tools Used

- `check_known_issues`
- `code_index`
- `code_stats`
- `code_watch`
- `knowledge_scan`
- `learn_tool_fix`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/knowledge_refresh.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/knowledge_refresh.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
