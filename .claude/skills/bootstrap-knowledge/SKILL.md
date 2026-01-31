---
name: bootstrap-knowledge
description: Scan a project and generate comprehensive knowledge for all personas
license: MIT
compatibility: opencode
metadata:
  version: "2.0"
  source: bootstrap_knowledge.yaml
  executable: "true"
---

# bootstrap_knowledge

Scan a project and generate comprehensive knowledge for all personas.

**NEW Features:**
- Creates semantic vector index for code search
- Performs deep analysis of code patterns
- Starts file watcher for automatic index updates
- Analyzes git history for contributor patterns

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("bootstrap_knowledge", '{
  "project": "example-project",
  "personas": "developer,devops,tester,release",
  "deep_scan": false,
  "create_vector_index": true,
  "start_watcher": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Check for known vector indexing issues before starting**
2. **detect_project**
3. **set_project**
4. **validate_project**
5. **get_project_path**
6. **parse_personas**
7. **scan_for_developer**
8. **scan_for_devops**
9. **scan_for_tester**
10. **scan_for_release**
11. **Create semantic vector index for code search**
12. **Parse vector index creation result**
13. **Start file watcher for automatic index updates**
14. **Analyze code patterns using semantic search**
15. **Parse pattern analysis results**
16. **Analyze error handling patterns**
17. **Parse error handling analysis**
18. **deep_scan_readme**
19. **deep_scan_tests**
20. **build_summary**
21. **Detect failure patterns from knowledge bootstrap**
22. **Learn from permission failures**
23. **Log knowledge bootstrap to session**
24. **Track knowledge bootstrap history**
25. **Update project knowledge state**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `-` | Project name from config.json (auto-detected from cwd if empty) |
| `personas` | string | No | `developer,devops,tester,release` | Comma-separated list of personas to generate knowledge for |
| `deep_scan` | boolean | No | `false` | If true, perform deeper analysis (slower but more comprehensive) |
| `create_vector_index` | boolean | No | `true` | If true, create semantic vector index for code search |
| `start_watcher` | boolean | No | `true` | If true, start file watcher for automatic index updates |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the bootstrap_knowledge skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("bootstrap_knowledge", '{
  "project": "example-project",
  "personas": "developer,devops,tester,release",
  "deep_scan": false,
  "create_vector_index": true,
  "start_watcher": true
}')
```

### Via Command (if configured)

```
/bootstrap-knowledge
```

## MCP Tools Used

- `check_known_issues`
- `code_index`
- `code_search`
- `code_watch`
- `knowledge_query`
- `knowledge_scan`
- `learn_tool_fix`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/bootstrap_knowledge.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/bootstrap_knowledge.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
