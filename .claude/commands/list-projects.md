---
name: list-projects
description: "List all configured projects in config.json."
---
# List Projects

List all configured projects in config.json.

## Instructions

```text
project_list()
```

## What It Shows

For each project:
- ✅/❌ Path exists status
- Project name
- Local filesystem path
- GitLab project path
- Jira project key
- Default branch
- Konflux namespace (if configured)
- Commit scopes

## Example Output

```
## 📁 Configured Projects

### ✅ automation-analytics-backend
- **Path:** `/home/user/src/automation-analytics-backend`
- **GitLab:** `automation-analytics/automation-analytics-backend`
- **Jira:** `AAP`
- **Branch:** `main`
- **Konflux:** `aap-aa-tenant`
- **Scopes:** api, billing, reports, ingestion, auth

### ✅ pdf-generator
- **Path:** `/home/user/src/pdf-generator`
- **GitLab:** `automation-analytics/pdf-generator`
- **Jira:** `AAP`
- **Branch:** `main`

*Total: 2 projects*
```

## Related Commands

- `/add-project` - Add a new project
- `/detect-project` - Auto-detect project settings
- `/remove-project` - Remove a project
