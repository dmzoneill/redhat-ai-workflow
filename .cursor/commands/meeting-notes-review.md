# Meeting Notes Review

Review meeting transcripts and extract action items.

## Instructions

```text
skill_run("meeting_notes_review", '{"meeting_id": "", "create_jira_issues": "", "search_query": "", "export_format": ""}')
```

## What It Does

Review meeting transcripts and extract action items.

This skill handles:
- Listing recent meetings
- Retrieving full transcripts
- Searching across meeting history
- AI-powered summary and action item extraction
- Exporting notes to various formats
- Searching Google Drive for related documents

Uses: meet_notes_list_meetings, meet_notes_get_transcript, meet_notes_search,
meet_notes_stats, meet_notes_export_state, meet_notes_active,
meet_notes_scheduler_status, ollama_generate, ollama_classify, gdrive_search

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `meeting_id` | Specific meeting ID to review | No |
| `create_jira_issues` | Create Jira issues from action items | No |
| `search_query` | Search query across meeting transcripts | No |
| `export_format` | Export format (markdown|json|text) (default: markdown) | No |
