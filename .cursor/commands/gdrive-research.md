# Gdrive Research

Search Google Drive for documents related to a topic or issue.

## Instructions

```text
skill_run("gdrive_research", '{"query": "$QUERY", "issue_key": "", "folder_id": "", "file_types": ""}')
```

## What It Does

Search Google Drive for documents related to a topic or issue.

Features:
- Full-text search across Google Drive
- Filter by file types (docs, sheets, slides, pdf)
- Browse recent files and folders
- Cross-reference with Gmail for related emails
- Get file metadata and sharing info

Uses: gdrive_search, gdrive_get_file_content, gdrive_get_file_info,
gdrive_list_recent, gdrive_list_files, gmail_search

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `query` | Search query for Google Drive | Yes |
| `issue_key` | Jira issue key to find related docs | No |
| `folder_id` | Google Drive folder ID to browse | No |
| `file_types` | Comma-separated file types to filter (e.g., 'document,spreadsheet,presentation') | No |
