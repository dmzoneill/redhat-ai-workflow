---
name: edit-slide-deck
description: Edit an existing Google Slides presentation
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: edit_slide_deck.yaml
  executable: "true"
---

# edit_slide_deck

Edit an existing Google Slides presentation.

This skill:
1. Gets the current presentation structure
2. Allows adding, updating, or deleting slides
3. Supports text updates and new content

Use this to modify existing presentations.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("edit_slide_deck", '{
  "presentation_id": "example-presentation_id",
  "action": "example-action",
  "slide_id": "example-slide_id",
  "object_id": "example-object_id",
  "layout": "TITLE_AND_BODY",
  "title": "example-title",
  "body": "example-body",
  "text": "example-text",
  "x": 100,
  "y": 100
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Get presentation details**
2. **Add a new slide**
3. **Update text in element**
4. **Delete a slide**
5. **Add a text box**
6. **build_summary**
7. **Log edit action to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `presentation_id` | string | Yes | `-` | The presentation ID to edit |
| `action` | string | Yes | `-` | Action to perform: - "view" - Show current slides - "add_slide" - Add a new slide - "update_text" - Update text in an element - "delete_slide" - Delete a slide - "add_text_box" - Add a text box  |
| `slide_id` | string | No | `-` | Slide ID for operations (required for some actions) |
| `object_id` | string | No | `-` | Element ID for text updates |
| `layout` | string | No | `TITLE_AND_BODY` | Layout for new slides |
| `title` | string | No | `-` | Title for new slide or text box |
| `body` | string | No | `-` | Body text for new slide |
| `text` | string | No | `-` | Text content for updates or text boxes |
| `x` | number | No | `100` | X position for text box |
| `y` | number | No | `100` | Y position for text box |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the edit_slide_deck skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("edit_slide_deck", '{
  "presentation_id": "example-presentation_id",
  "action": "example-action",
  "slide_id": "example-slide_id",
  "object_id": "example-object_id",
  "layout": "TITLE_AND_BODY",
  "title": "example-title",
  "body": "example-body",
  "text": "example-text",
  "x": 100,
  "y": 100
}')
```

### Via Command (if configured)

```
/edit-slide-deck
```

## MCP Tools Used

- `google_slides_add_slide`
- `google_slides_add_text_box`
- `google_slides_delete_slide`
- `google_slides_get`
- `google_slides_update_text`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/edit_slide_deck.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/edit_slide_deck.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
