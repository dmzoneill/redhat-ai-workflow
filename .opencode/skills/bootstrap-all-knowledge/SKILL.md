---
name: bootstrap-all-knowledge
description: Iterate all configured projects and all available personas to build project knowledge
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: bootstrap_all_knowledge.yaml
  executable: "true"
---

# bootstrap_all_knowledge

Iterate all configured projects and all available personas to build project knowledge.

This skill:
1. Gets all configured projects from config.json (dynamic)
2. Gets all available personas from personas/*.yaml (dynamic)
3. For each project/persona combination:
   - Skip if knowledge already exists (unless force=true)
   - Run knowledge_scan to generate knowledge
4. Reports summary of all operations

Use this skill to:
- Initialize knowledge for all projects at once
- Ensure all personas have knowledge for all projects
- Scheduled via cron for automatic maintenance

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("bootstrap_all_knowledge", '{
  "force": false,
  "projects": "example-projects",
  "personas": "example-personas",
  "skip_existing": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Get list of all configured projects**
2. **Get list of all available personas dynamically**
3. **Check which project/persona combinations already have knowledge**
4. **Generate knowledge for all missing project/persona combinations**
5. **Build summary report**
6. **Log the bootstrap to session memory**
7. **Track bootstrap in learned patterns**
8. **Update knowledge state tracking**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `force` | boolean | No | `false` | If true, regenerate all knowledge even if it exists |
| `projects` | string | No | `-` | Comma-separated list of projects. If empty, process all configured projects. |
| `personas` | string | No | `-` | Comma-separated list of personas. If empty, use default knowledge personas. |
| `skip_existing` | boolean | No | `true` | If true, skip project/persona combinations that already have knowledge |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the bootstrap_all_knowledge skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("bootstrap_all_knowledge", '{
  "force": false,
  "projects": "example-projects",
  "personas": "example-personas",
  "skip_existing": true
}')
```

### Via Command (if configured)

```
/bootstrap-all-knowledge
```

## MCP Tools Used

- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/bootstrap_all_knowledge.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/bootstrap_all_knowledge.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
