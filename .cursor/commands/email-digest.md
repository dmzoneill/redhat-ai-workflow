# Email Digest

Generate a categorized email digest from Gmail.

## Instructions

```text
skill_run("email_digest", '{"since": "", "labels": "", "search_query": ""}')
```

## What It Does

Generate a categorized email digest from Gmail.

Features:
- Fetch unread emails from a configurable time window
- Categorize by labels and content type
- Search for specific emails
- Show actionable items requiring response

Uses: gmail_unread_count, gmail_list_emails, gmail_search,
gmail_read_email, gmail_get_thread, gmail_list_labels

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `since` | Hours back to look for emails (default: 24) (default: 24) | No |
| `labels` | Comma-separated labels to filter by | No |
| `search_query` | Optional Gmail search query | No |
