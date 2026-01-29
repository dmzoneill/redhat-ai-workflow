---
name: edit-slide-deck
description: "Edit an existing Google Slides presentation."
arguments:
  - name: presentation_id
    required: true
  - name: action
    required: true
  - name: slide_id
  - name: object_id
  - name: layout
  - name: title
  - name: body
  - name: text
  - name: x
  - name: y
---
# Edit Slide Deck

Edit an existing Google Slides presentation.

## Instructions

```text
skill_run("edit_slide_deck", '{"presentation_id": "$PRESENTATION_ID", "action": "$ACTION", "slide_id": "", "object_id": "", "layout": "", "title": "", "body": "", "text": "", "x": "", "y": ""}')
```

## What It Does

Edit an existing Google Slides presentation.

This skill:
1. Gets the current presentation structure
2. Allows adding, updating, or deleting slides
3. Supports text updates and new content

Use this to modify existing presentations.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `presentation_id` | The presentation ID to edit | Yes |
| `action` | Action to perform:
- "view" - Show current slides
- "add_slide" - Add a new slide
- "update_text" - Update text in an element
- "delete_slide" - Delete a slide
- "add_text_box" - Add a text box
 | Yes |
| `slide_id` | Slide ID for operations (required for some actions) | No |
| `object_id` | Element ID for text updates | No |
| `layout` | Layout for new slides (default: TITLE_AND_BODY) | No |
| `title` | Title for new slide or text box | No |
| `body` | Body text for new slide | No |
| `text` | Text content for updates or text boxes | No |
| `x` | X position for text box (default: 100) | No |
| `y` | Y position for text box (default: 100) | No |
