---
name: add-project
description: Add a new project to config.json with auto-detection and validation
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: add_project.yaml
  executable: "true"
---

# add_project

Add a new project to config.json with auto-detection and validation.

This skill:
1. Detects project settings from the directory
2. Validates GitLab and Jira access
3. Adds the project to config.json
4. Optionally configures Quay and Bonfire integrations
5. Generates initial project knowledge

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("add_project", '{
  "path": "example-path",
  "name": "example-name",
  "gitlab": "example-gitlab",
  "jira_project": "example-jira_project",
  "jira_component": "example-jira_component",
  "konflux_namespace": "example-konflux_namespace",
  "setup_quay": false,
  "setup_bonfire": false,
  "generate_knowledge": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load project persona for project management tools**
2. **Check for known GitLab issues before starting**
3. **Auto-detect project settings from directory**
4. **Verify the project path exists**
5. **Determine project name**
6. **Verify GitLab project is accessible**
7. **Verify Jira project is accessible**
8. **Add project to config.json**
9. **Add Quay repository configuration**
10. **Add Bonfire app configuration**
11. **Generate initial project knowledge**
12. **Create semantic vector index for the project**
13. **Start file watcher for automatic index updates**
14. **Summarize what was done**
15. **Detect failure patterns from project setup**
16. **Learn from VPN failures**
17. **Log project addition to session**
18. **Track project additions in memory**
19. **Update projects state in memory**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `path` | string | Yes | `-` | Path to the project directory |
| `name` | string | No | `-` | Project name (defaults to directory name) |
| `gitlab` | string | No | `-` | GitLab project path (auto-detected if not provided) |
| `jira_project` | string | Yes | `-` | Jira project key (e.g., AAP, KONFLUX) |
| `jira_component` | string | No | `-` | Jira component name |
| `konflux_namespace` | string | No | `-` | Konflux tenant namespace (if using Konflux CI) |
| `setup_quay` | boolean | No | `false` | Configure Quay repository |
| `setup_bonfire` | boolean | No | `false` | Configure Bonfire/ephemeral deployment |
| `generate_knowledge` | boolean | No | `true` | Generate initial project knowledge |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the add_project skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("add_project", '{
  "path": "example-path",
  "name": "example-name",
  "gitlab": "example-gitlab",
  "jira_project": "example-jira_project",
  "jira_component": "example-jira_component",
  "konflux_namespace": "example-konflux_namespace",
  "setup_quay": false,
  "setup_bonfire": false,
  "generate_knowledge": true
}')
```

### Via Command (if configured)

```
/add-project
```

## MCP Tools Used

- `check_known_issues`
- `code_index`
- `code_watch`
- `gitlab_mr_list`
- `jira_list_issues`
- `knowledge_scan`
- `learn_tool_fix`
- `memory_append`
- `memory_session_log`
- `persona_load`
- `project_add`
- `project_detect`
- `shell`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/add_project.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/add_project.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
