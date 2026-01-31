---
name: learn-architecture
description: Deep scan of project structure to update architecture knowledge
license: MIT
compatibility: opencode
metadata:
  version: "2.0"
  source: learn_architecture.yaml
  executable: "true"
---

# learn_architecture

Deep scan of project structure to update architecture knowledge.

**NEW Features:**
- Uses semantic code search to discover patterns
- Identifies code relationships and dependencies
- Analyzes error handling patterns
- Discovers API endpoints and data models

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("learn_architecture", '{
  "project": "example-project",
  "persona": "example-persona",
  "focus": "example-focus",
  "use_vector_search": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Check for known vector search issues before starting**
2. **detect_context**
3. **get_project_path**
4. **scan_directory_structure**
5. **analyze_key_modules**
6. **analyze_dependencies**
7. **Search for API endpoint patterns**
8. **Parse API pattern search results**
9. **Search for data model patterns**
10. **Parse model pattern search results**
11. **Search for error handling patterns**
12. **Parse error pattern search results**
13. **Search for testing patterns**
14. **Parse test pattern search results**
15. **Search for patterns in focus area**
16. **Parse focus area search results**
17. **update_knowledge**
18. **update_dependencies**
19. **Track architecture learning history**
20. **Update project architecture state in memory**
21. **build_result**
22. **Detect failure patterns from architecture learning**
23. **Learn from vector index failures**
24. **Log architecture learning to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `-` | Project name from config.json (auto-detected from cwd if empty) |
| `persona` | string | No | `-` | Persona to update (uses current persona if empty) |
| `focus` | string | No | `-` | Specific area to focus on (e.g., "api", "tests", "models") |
| `use_vector_search` | boolean | No | `true` | Use semantic vector search for deeper pattern discovery |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the learn_architecture skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("learn_architecture", '{
  "project": "example-project",
  "persona": "example-persona",
  "focus": "example-focus",
  "use_vector_search": true
}')
```

### Via Command (if configured)

```
/learn-architecture
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `knowledge_update`
- `learn_tool_fix`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/learn_architecture.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/learn_architecture.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
