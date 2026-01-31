---
name: reindex-all-vectors
description: Reindex all vector databases for all configured projects
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: reindex_all_vectors.yaml
  executable: "true"
---

# reindex_all_vectors

Reindex all vector databases for all configured projects.

This skill iterates through all repositories in config.json and
updates their vector indexes for semantic code search.

Use this skill to:
- Keep all vector indexes fresh
- Ensure semantic search works across all projects
- Scheduled hourly via cron for automatic maintenance

The skill:
1. Gets list of all configured repositories
2. For each project, runs code_index to update vectors
3. Restarts file watchers for automatic updates
4. Reports summary of all indexing operations

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("reindex_all_vectors", '{
  "force": false,
  "projects": "example-projects",
  "restart_watchers": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Get list of all configured projects**
2. **Reindex all projects**
3. **Restart file watchers for indexed projects**
4. **Build summary report**
5. **Log the reindex to session memory**
6. **Track reindex in learned patterns**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `force` | boolean | No | `false` | If true, force full re-index of all files (not just changed) |
| `projects` | string | No | `-` | Comma-separated list of projects to reindex. If empty, reindex all. |
| `restart_watchers` | boolean | No | `true` | If true, restart file watchers after indexing |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the reindex_all_vectors skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("reindex_all_vectors", '{
  "force": false,
  "projects": "example-projects",
  "restart_watchers": true
}')
```

### Via Command (if configured)

```
/reindex-all-vectors
```

## MCP Tools Used

- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/reindex_all_vectors.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/reindex_all_vectors.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
