---
name: list-presentations
description: List Google Slides presentations from your Drive
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: list_presentations.yaml
  executable: "true"
---

# list_presentations

List Google Slides presentations from your Drive.

This skill:
1. Queries Google Drive for presentation files
2. Returns a formatted list with IDs and links
3. Optionally filters by search query

Use this to find existing presentations to edit or reference.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("list_presentations", '{
  "search": "example-search",
  "max_results": 20
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **List Google Slides presentations**
2. **build_summary**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `search` | string | No | `-` | Search term to filter presentations by name |
| `max_results` | integer | No | `20` | Maximum number of presentations to return |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the list_presentations skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("list_presentations", '{
  "search": "example-search",
  "max_results": 20
}')
```

### Via Command (if configured)

```
/list-presentations
```

## MCP Tools Used

- `google_slides_list`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/list_presentations.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/list_presentations.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
