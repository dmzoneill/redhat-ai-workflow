# Skill: create_slide_deck

> Create a new Google Slides presentation

## Overview

Creates a new Google Slides presentation, optionally from an outline or topic.

## Usage

```python
skill_run("create_slide_deck", '{"title": "My Presentation"}')
```

## Inputs

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| title | string | Yes | Title for the new presentation |
| outline | string | No | Markdown-style outline for slides |
| template_id | string | No | Presentation ID to use as template |
| topic | string | No | Topic to research and generate outline from |

## Outline Format

Use markdown headings to define slide structure:

```markdown
# Section Title
Creates a section header slide

## Slide Title
Creates a title and body slide

- Bullet point
- Another bullet
  - Sub-bullet
```

## Examples

### Blank Presentation

```python
skill_run("create_slide_deck", '{"title": "Project Update"}')
```

### From Outline

```python
skill_run("create_slide_deck", '{
  "title": "AI Workflow Overview",
  "outline": "# Introduction\\n## What is AI Workflow?\\n- Tool automation\\n- Persona system\\n# Architecture\\n## Components\\n- MCP Server\\n- Skills\\n- Memory"
}')
```

### From Template

```python
skill_run("create_slide_deck", '{
  "title": "Q1 Review",
  "template_id": "1abc123def456..."
}')
```

### From Topic (Auto-generate)

```python
skill_run("create_slide_deck", '{
  "title": "MCP Protocol Deep Dive",
  "topic": "Model Context Protocol"
}')
```

## Output

Returns:
- Presentation ID
- Link to edit in Google Slides
- Number of slides created (if from outline)

## Workflow

1. Creates new presentation (blank or from template)
2. If outline provided, builds slides from markdown
3. If topic provided, researches and generates outline
4. Logs creation to session memory

## Related Skills

- `list_presentations` - List existing presentations
- `edit_slide_deck` - Edit presentation content
- `export_presentation` - Export to PDF

## See Also

- [Google Slides Tool Module](../tool-modules/google_slides.md)
- [Presentations Persona](../personas/presentations.md)
