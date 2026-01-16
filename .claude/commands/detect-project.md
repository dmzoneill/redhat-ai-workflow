---
name: detect-project
description: "Auto-detect project settings from a directory."
---
# Detect Project

Auto-detect project settings from a directory.

## Instructions

```text
project_detect(path="$PROJECT_PATH")
```

## What It Detects

- **Language**: Python, JavaScript, Go, Rust, Java
- **Default branch**: From `git symbolic-ref refs/remotes/origin/HEAD`
- **GitLab remote**: Parsed from `git remote get-url origin`
- **Lint command**: Based on config files (pyproject.toml, package.json)
- **Test command**: Based on test framework detection
- **Scopes**: From directory structure (api, core, tests, etc.)
- **Test setup**: Generated instructions based on language

## Example

```bash
# Detect settings for a project
project_detect(path="/home/user/src/my-new-project")
```

## Example Output

```
## 🔍 Detected Project Settings: my-new-project

**Language:** python
**Path:** `/home/user/src/my-new-project`
**Default Branch:** `main`
**GitLab:** `myorg/my-new-project`
**Lint Command:** `black --check . && flake8 .`
**Test Command:** `pytest tests/ -v`
**Scopes:** api, core, tests, utils

### Suggested Config Entry

{
  "my-new-project": {
    "path": "/home/user/src/my-new-project",
    "gitlab": "myorg/my-new-project",
    "jira_project": "<PROJECT_KEY>",
    ...
  }
}

*Use `project_add()` to add this project to config.json*
```

## Next Steps

After detection, use `/add-project` to add the project:

```bash
project_add(
    name="my-new-project",
    path="/home/user/src/my-new-project",
    gitlab="myorg/my-new-project",
    jira_project="AAP"
)
```

## See Also

- `/add-project` - Add project to config
- `/list-projects` - List configured projects
