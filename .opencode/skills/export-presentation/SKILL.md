---
name: export-presentation
description: Export a Google Slides presentation to PDF format
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: export_presentation.yaml
  executable: "true"
---

# export_presentation

Export a Google Slides presentation to PDF format.

This skill:
1. Exports the presentation to PDF
2. Saves to the specified path or default location
3. Returns the file path

Use this to create shareable PDF versions of presentations.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("export_presentation", '{
  "presentation_id": "example-presentation_id",
  "output_path": "example-output_path"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Export presentation to PDF**
2. **build_summary**
3. **Log export to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `presentation_id` | string | Yes | `-` | The presentation ID to export |
| `output_path` | string | No | `-` | Output file path (default: uses presentation title) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the export_presentation skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("export_presentation", '{
  "presentation_id": "example-presentation_id",
  "output_path": "example-output_path"
}')
```

### Via Command (if configured)

```
/export-presentation
```

## MCP Tools Used

- `google_slides_export_pdf`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/export_presentation.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/export_presentation.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
