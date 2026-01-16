# Add Project

Add a new project to config.json with auto-detection.

## Instructions

```text
skill_run("add_project", '{"path": "$PROJECT_PATH", "jira_project": "$JIRA_PROJECT"}')
```

This will:
1. Auto-detect project settings (language, branch, lint/test commands)
2. Validate GitLab and Jira access
3. Add the project to config.json
4. Optionally generate project knowledge

## Quick Add

For a quick add with auto-detection:

```bash
# Detect settings first
project_detect(path="/path/to/project")

# Then add
project_add(
    name="my-project",
    path="/path/to/project",
    gitlab="org/my-project",
    jira_project="AAP"
)
```

## Full Skill

Use the skill for the complete workflow:

```bash
skill_run("add_project", '{
    "path": "/home/user/src/new-service",
    "jira_project": "AAP",
    "jira_component": "New Service",
    "konflux_namespace": "my-tenant",
    "setup_quay": true,
    "generate_knowledge": true
}')
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `path` | ✅ | Path to project directory |
| `name` | ⚪ | Project name (defaults to dir name) |
| `gitlab` | ⚪ | GitLab path (auto-detected) |
| `jira_project` | ✅ | Jira project key |
| `jira_component` | ⚪ | Jira component name |
| `konflux_namespace` | ⚪ | Konflux tenant namespace |
| `setup_quay` | ⚪ | Configure Quay repository |
| `setup_bonfire` | ⚪ | Configure Bonfire deployment |
| `generate_knowledge` | ⚪ | Generate project knowledge (default: true) |

## Auto-Detection

The tool detects:
- **Language**: Python, JavaScript, Go, Rust, Java
- **Default branch**: From git remote
- **GitLab remote**: From git origin URL
- **Lint command**: From pyproject.toml, package.json, etc.
- **Test command**: From test framework config
- **Scopes**: From directory structure

## See Also

- `/list-projects` - List configured projects
- `/knowledge-scan` - Scan project for knowledge
- `/bootstrap-knowledge` - Full knowledge generation
