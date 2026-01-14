---
description: Check and update repository documentation
---

# Update Documentation

Check repository documentation for staleness and get suggestions for updates.

## What This Does

1. Scans for changed files in the current branch
2. Checks README.md for broken links
3. Reviews API docs if endpoints changed
4. Checks mermaid diagrams if architecture changed
5. Reports issues and suggestions

## Usage

Check documentation in current repo:

```text
skill_run("update_docs", '{"check_only": true}')
```

Check a specific repository:

```text
skill_run("update_docs", '{"repo_name": "automation-analytics-backend", "check_only": true}')
```

With issue key for potential commits:

```text
skill_run("update_docs", '{"issue_key": "AAP-12345", "check_only": false}')
```

## Config

Requires `docs` config in the repository's config.json entry:

```json
"docs": {
  "enabled": true,
  "path": "docs/",
  "readme": "README.md",
  "api_docs": "docs/api/",
  "architecture": "docs/architecture/",
  "diagrams": ["docs/architecture/*.md"],
  "auto_update": true,
  "check_on_mr": true
}
```

## Integration

This skill is automatically run by:
- `create_mr` - checks docs before creating MR
- `mark_mr_ready` - checks docs before marking ready

Use `check_docs: false` to skip in those skills.
