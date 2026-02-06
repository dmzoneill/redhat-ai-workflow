# Slack Persona Sync

Sync Slack messages to persona vector store.

## Instructions

```text
skill_run("slack_persona_sync", '{"mode": "", "months": "", "days": "", "include_threads": ""}')
```

## What It Does

Sync Slack messages to persona vector store.

This skill syncs all messages from all channels, DMs, group chats, and threads
to a vector database for semantic search. Used to provide context to the
Dave persona for more authentic responses.

Modes:
- full: Complete resync of all messages within time window
- incremental: Sync only recent messages and prune old ones

The vector store maintains a rolling window (default 6 months) of messages
that can be searched semantically.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `mode` | Sync mode: 'full' or 'incremental' (default: incremental) | No |
| `months` | Time window in months (for full sync) (default: 48) | No |
| `days` | Days to sync (for incremental) (default: 1) | No |
| `include_threads` | Include thread replies (default: True) | No |
