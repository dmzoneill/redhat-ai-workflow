# List Presentations

List Google Slides presentations from your Drive.

## Instructions

```text
skill_run("list_presentations", '{"search": "", "max_results": ""}')
```

## What It Does

List Google Slides presentations from your Drive.

This skill:
1. Queries Google Drive for presentation files
2. Returns a formatted list with IDs and links
3. Optionally filters by search query

Use this to find existing presentations to edit or reference.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `search` | Search term to filter presentations by name | No |
| `max_results` | Maximum number of presentations to return (default: 20) | No |
