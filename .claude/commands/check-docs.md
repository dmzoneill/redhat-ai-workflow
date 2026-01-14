---
description: Check repository documentation for staleness
---

# Check Documentation

Check if repository documentation needs updating based on code changes.

## What This Does

1. Scans for changed files in the current branch
2. Checks README.md for broken links
3. Reviews API docs if endpoints changed
4. Checks mermaid diagrams if architecture changed
5. Reports issues and suggestions

## Usage

Run the update_docs skill to check documentation:

```text
skill_run("update_docs", '{"repo": ".", "check_only": true}')
```

Or for a specific repository:

```text
skill_run("update_docs", '{"repo_name": "automation-analytics-backend", "check_only": true}')
```

## Notes

- Only runs for repos with `docs.enabled=true` in config.json
- Integrated into `create_mr` and `mark_mr_ready` skills
- Use `check_only: true` to just check, `check_only: false` for suggestions
