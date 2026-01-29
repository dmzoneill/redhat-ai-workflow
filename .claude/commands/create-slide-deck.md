---
name: create-slide-deck
description: "Create a new Google Slides presentation."
arguments:
  - name: title
    required: true
  - name: topic
    required: true
---
# Create Slide Deck

Create a new Google Slides presentation.

## Instructions

```text
skill_run("create_slide_deck", '{"title": "$TITLE", "topic": "$TOPIC"}')
```

## What It Does

Create a new Google Slides presentation.

This skill:
1. Creates a new presentation (optionally from template)
2. Builds slides from a markdown outline if provided
3. Returns the presentation link for editing

Use this when you need to create a new presentation from scratch or outline.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `title` | Title for the new presentation | Yes |
| `outline` | Markdown-style outline for slides:
# Section Title (creates section header)
## Slide Title (creates title+body slide)
- Bullet point
 | No |
| `template_id` | Optional presentation ID to use as template | No |
| `topic` | Topic to research and generate outline from (if no outline provided) | No |

## Examples

```bash
# Create from topic (auto-generates outline)
skill_run("create_slide_deck", '{"title": "AI Workflow Overview", "topic": "AI development workflows"}')

# Create from outline
skill_run("create_slide_deck", '{"title": "My Presentation", "outline": "# Title\n## Slide 1\n- Point 1"}')
```
