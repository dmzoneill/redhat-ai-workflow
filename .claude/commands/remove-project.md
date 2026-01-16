---
name: remove-project
description: "Remove a project from config.json."
---
# Remove Project

Remove a project from config.json.

## Instructions

```text
project_remove(name="$PROJECT_NAME", confirm=True)
```

## Safety

By default, removal requires confirmation:

```bash
# First call shows what will be removed
project_remove(name="my-project")

# Second call with confirm=True actually removes
project_remove(name="my-project", confirm=True)
```

## What Gets Removed

- Entry from `repositories` section
- Entry from `quay.repositories` (if present)
- Entry from `saas_pipelines.namespaces` (if present)

## Example

```bash
# Check what will be removed
project_remove(name="old-service")

# Output:
# ⚠️ **Confirm removal of project 'old-service'**
#
# ### Current Configuration
# {
#   "old-service": {
#     "path": "/home/user/src/old-service",
#     ...
#   }
# }
#
# *Run `project_remove('old-service', confirm=True)` to confirm removal.*

# Actually remove
project_remove(name="old-service", confirm=True)
```

## See Also

- `/list-projects` - List configured projects
- `/add-project` - Add a new project
