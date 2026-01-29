---
name: export-presentation
description: "Export a Google Slides presentation to PDF format."
arguments:
  - name: presentation_id
    required: true
  - name: output_path
---
# Export Presentation

Export a Google Slides presentation to PDF format.

## Instructions

```text
skill_run("export_presentation", '{"presentation_id": "$PRESENTATION_ID", "output_path": ""}')
```

## What It Does

Export a Google Slides presentation to PDF format.

This skill:
1. Exports the presentation to PDF
2. Saves to the specified path or default location
3. Returns the file path

Use this to create shareable PDF versions of presentations.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `presentation_id` | The presentation ID to export | Yes |
| `output_path` | Output file path (default: uses presentation title) | No |
