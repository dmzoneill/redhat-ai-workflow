---
name: create-slide-deck
description: Create a new Google Slides presentation
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: create_slide_deck.yaml
  executable: "true"
---

# create_slide_deck

Create a new Google Slides presentation.

This skill:
1. Creates a new presentation (optionally from template)
2. Builds slides from a markdown outline if provided
3. Returns the presentation link for editing

Use this when you need to create a new presentation from scratch or outline.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("create_slide_deck", '{
  "title": "example-title",
  "outline": "example-outline",
  "template_id": "example-template_id",
  "topic": "example-topic"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Create new Google Slides presentation**
2. **Extract presentation ID from result**
3. **Research topic for outline generation**
4. **Generate outline from research**
5. **Use provided outline**
6. **Build slides from outline**
7. **build_summary**
8. **Log presentation creation to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `title` | string | Yes | `-` | Title for the new presentation |
| `outline` | string | No | `-` | Markdown-style outline for slides: # Section Title (creates section header) ## Slide Title (creates title+body slide) - Bullet point  |
| `template_id` | string | No | `-` | Optional presentation ID to use as template |
| `topic` | string | No | `-` | Topic to research and generate outline from (if no outline provided) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the create_slide_deck skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("create_slide_deck", '{
  "title": "example-title",
  "outline": "example-outline",
  "template_id": "example-template_id",
  "topic": "example-topic"
}')
```

### Via Command (if configured)

```
/create-slide-deck
```

## MCP Tools Used

- `google_slides_build_from_outline`
- `google_slides_create`
- `knowledge_query`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/create_slide_deck.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/create_slide_deck.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
