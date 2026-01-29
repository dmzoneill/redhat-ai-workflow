# Google Slides Tool Module

> Create and manage Google Slides presentations from the command line

## Overview

The `aa_google_slides` tool module provides MCP tools for creating, editing, and managing Google Slides presentations. It integrates with the existing Google OAuth setup used by Google Calendar.

## Features

- **List presentations** from Google Drive
- **Create presentations** from scratch or templates
- **Add/edit/delete slides** with various layouts
- **Update text content** in slides
- **Add text boxes** at specific positions
- **Export to PDF** for sharing
- **Build from outline** using markdown syntax

## Setup

Google Slides uses the same OAuth credentials as Google Calendar. If Calendar is already working, Slides should work automatically.

### If not authenticated:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable **Google Slides API** and **Google Drive API**
3. Delete `~/.config/google_calendar/token.json` to force re-authentication
4. Run `google_slides_status()` to authenticate with new scopes

### Required Scopes

```
https://www.googleapis.com/auth/presentations
https://www.googleapis.com/auth/presentations.readonly
https://www.googleapis.com/auth/drive.file
https://www.googleapis.com/auth/drive.readonly
```

## Tools

### google_slides_status

Check API connection status.

```python
google_slides_status()
```

### google_slides_list

List presentations from Google Drive.

```python
google_slides_list(max_results=20, search_query="")
```

| Parameter | Type | Description |
|-----------|------|-------------|
| max_results | int | Maximum presentations to return (default: 20) |
| search_query | str | Filter by name |

### google_slides_get

Get details of a specific presentation.

```python
google_slides_get(presentation_id="1abc...")
```

### google_slides_create

Create a new presentation.

```python
google_slides_create(title="My Presentation", template_id="")
```

| Parameter | Type | Description |
|-----------|------|-------------|
| title | str | Presentation title |
| template_id | str | Optional template to copy from |

### google_slides_add_slide

Add a new slide to a presentation.

```python
google_slides_add_slide(
    presentation_id="1abc...",
    layout="TITLE_AND_BODY",
    title="Slide Title",
    body="Bullet points here"
)
```

**Available Layouts:**
- `BLANK` - Empty slide
- `TITLE` - Title slide
- `TITLE_AND_BODY` - Title with bullet points
- `TITLE_AND_TWO_COLUMNS` - Two column layout
- `TITLE_ONLY` - Just a title
- `SECTION_HEADER` - Section divider
- `ONE_COLUMN_TEXT` - Single column text
- `MAIN_POINT` - Key message slide
- `BIG_NUMBER` - Highlight a statistic

### google_slides_update_text

Update text in a slide element.

```python
google_slides_update_text(
    presentation_id="1abc...",
    object_id="element_id",
    text="New content"
)
```

### google_slides_delete_slide

Delete a slide from a presentation.

```python
google_slides_delete_slide(
    presentation_id="1abc...",
    slide_id="slide_xyz"
)
```

### google_slides_add_text_box

Add a text box at a specific position.

```python
google_slides_add_text_box(
    presentation_id="1abc...",
    slide_id="slide_xyz",
    text="Custom text",
    x=100,
    y=100,
    width=300,
    height=50
)
```

### google_slides_export_pdf

Export presentation to PDF.

```python
google_slides_export_pdf(
    presentation_id="1abc...",
    output_path="~/presentations/output.pdf"
)
```

### google_slides_build_from_outline

Build slides from markdown outline.

```python
google_slides_build_from_outline(
    presentation_id="1abc...",
    outline="""
# Section Title
## Slide Title
- Bullet point 1
- Bullet point 2
"""
)
```

## Skills

### create_slide_deck

Create a new presentation with optional outline.

```python
skill_run("create_slide_deck", '{"title": "My Presentation", "outline": "# Intro\n## Overview"}')
```

### list_presentations

List all presentations.

```python
skill_run("list_presentations", '{"search": "AI"}')
```

### edit_slide_deck

Edit an existing presentation.

```python
skill_run("edit_slide_deck", '{"presentation_id": "1abc...", "action": "view"}')
```

Actions: `view`, `add_slide`, `update_text`, `delete_slide`, `add_text_box`

### export_presentation

Export to PDF.

```python
skill_run("export_presentation", '{"presentation_id": "1abc..."}')
```

## Persona

Load the presentations persona for all slide tools:

```python
persona_load("presentations")
```

## VSCode Extension

The Slides tab in the AI Workflow sidebar provides:

- **My Presentations** - List of your presentations
- **Actions** - Quick actions for creating and managing slides
- **Templates** - Saved templates for quick creation

## Example Workflow

```python
# 1. Load persona
persona_load("presentations")

# 2. Create presentation
google_slides_create("AI Workflow Overview")

# 3. Add slides
google_slides_add_slide(pres_id, "TITLE", "AI Workflow", "A Developer's Guide")
google_slides_add_slide(pres_id, "SECTION_HEADER", "Architecture")
google_slides_add_slide(pres_id, "TITLE_AND_BODY", "Key Components",
    "• Personas\n• Skills\n• Memory")

# 4. Export
google_slides_export_pdf(pres_id, "~/presentations/ai-workflow.pdf")
```

## See Also

- [Google Calendar](./google_calendar.md) - Shared OAuth setup
- [Presentations Persona](../personas/presentations.md) - Full persona documentation
- [Skills Reference](../skills/README.md) - All available skills
