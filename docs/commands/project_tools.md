# Project Tools

Tools for managing projects in `config.json`.

## Overview

These tools help you add, list, update, and remove projects from the workflow configuration. They support auto-detection of project settings from the filesystem.

## Tools

### `project_list`

List all configured projects.

```
project_list()
```

Shows:
- Project name and path
- GitLab and Jira configuration
- Default branch
- Status (✅ if path exists, ❌ if missing)

### `project_detect`

Auto-detect project settings from a directory.

```
project_detect(path="/path/to/project")
```

Detects:
- **Language**: Python, JavaScript, Go, Rust, Java
- **Default branch**: From git remote HEAD
- **GitLab remote**: From git origin URL
- **Lint command**: Based on config files (pyproject.toml, package.json, etc.)
- **Test command**: Based on test framework detection
- **Scopes**: From directory structure

Returns a suggested config entry that can be used with `project_add`.

### `project_add`

Add a new project to config.json.

```
project_add(
    name="my-project",
    path="/home/user/src/my-project",
    gitlab="org/my-project",
    jira_project="AAP",
    jira_component="My Component",  # optional
    lint_command="",                # auto-detected if empty
    test_command="",                # auto-detected if empty
    default_branch="main",          # auto-detected if empty
    konflux_namespace="",           # optional
    scopes="api,core,tests",        # comma-separated, auto-detected if empty
    auto_detect=True                # enable auto-detection
)
```

If `auto_detect=True` (default), empty fields will be populated from the project directory.

### `project_update`

Update an existing project's configuration.

```
project_update(
    name="my-project",
    lint_command="ruff check .",    # only updates provided fields
    test_command="pytest -v"
)
```

Only updates fields that are provided (non-empty).

### `project_remove`

Remove a project from config.json.

```
project_remove(name="my-project")           # shows confirmation prompt
project_remove(name="my-project", confirm=True)  # actually removes
```

Also removes the project from related sections:
- `quay.repositories`
- `saas_pipelines.namespaces`

## Skill: `add_project`

Interactive workflow for adding a project with validation.

```
skill_run("add_project", '{
    "path": "/home/user/src/my-project",
    "jira_project": "AAP",
    "generate_knowledge": true
}')
```

### Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `path` | ✅ | Path to project directory |
| `name` | ⚪ | Project name (defaults to directory name) |
| `gitlab` | ⚪ | GitLab path (auto-detected) |
| `jira_project` | ✅ | Jira project key |
| `jira_component` | ⚪ | Jira component name |
| `konflux_namespace` | ⚪ | Konflux tenant namespace |
| `setup_quay` | ⚪ | Configure Quay repository |
| `setup_bonfire` | ⚪ | Configure Bonfire deployment |
| `generate_knowledge` | ⚪ | Generate project knowledge (default: true) |

### Steps

1. **detect_settings** - Auto-detect project settings
2. **validate_path** - Verify path exists
3. **get_project_name** - Determine project name
4. **check_gitlab_access** - Verify GitLab is accessible
5. **check_jira_access** - Verify Jira project exists
6. **add_project** - Add to config.json
7. **setup_quay_repo** - Configure Quay (if requested)
8. **setup_bonfire_app** - Configure Bonfire (if requested)
9. **generate_project_knowledge** - Scan and generate knowledge
10. **summary** - Show what was done

## Config.json Structure

Each project in `repositories` has these fields:

```json
{
  "repositories": {
    "my-project": {
      "path": "/home/user/src/my-project",
      "gitlab": "org/my-project",
      "jira_project": "AAP",
      "jira_component": "My Component",
      "lint_command": "black --check . && flake8 .",
      "test_command": "pytest tests/ -v",
      "test_setup": "# Setup instructions...",
      "default_branch": "main",
      "konflux_namespace": "my-tenant",
      "scopes": ["api", "core", "tests"],
      "docs": {
        "enabled": true,
        "path": "docs/",
        "readme": "README.md"
      }
    }
  }
}
```

### Required Fields

| Field | Description |
|-------|-------------|
| `path` | Local filesystem path |
| `gitlab` | GitLab project path (e.g., `org/repo`) |
| `jira_project` | Jira project key (e.g., `AAP`) |
| `default_branch` | Default branch (main/master) |

### Optional Fields

| Field | Description |
|-------|-------------|
| `jira_component` | Jira component name |
| `lint_command` | Command to run linting |
| `test_command` | Command to run tests |
| `test_setup` | Test setup instructions |
| `konflux_namespace` | Konflux tenant namespace |
| `scopes` | Valid commit scopes |
| `docs` | Documentation configuration |

## Examples

### Add a Python Project

```
# First, detect settings
project_detect(path="/home/user/src/my-api")

# Then add with auto-detection
project_add(
    name="my-api",
    path="/home/user/src/my-api",
    gitlab="myorg/my-api",
    jira_project="MYPROJ"
)
```

### Add a Node.js Project

```
project_add(
    name="my-frontend",
    path="/home/user/src/my-frontend",
    gitlab="myorg/my-frontend",
    jira_project="MYPROJ",
    lint_command="npm run lint",
    test_command="npm test",
    default_branch="main"
)
```

### Use the Skill

```
skill_run("add_project", '{
    "path": "/home/user/src/new-service",
    "jira_project": "AAP",
    "jira_component": "New Service",
    "konflux_namespace": "my-tenant",
    "setup_quay": true,
    "generate_knowledge": true
}')
```
