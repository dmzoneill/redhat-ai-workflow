---
name: discovered-work-summary
description: Generate a summary of discovered work for daily standups or weekly reports
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: discovered_work_summary.yaml
  executable: "true"
---

# discovered_work_summary

Generate a summary of discovered work for daily standups or weekly reports.

This skill:
1. Retrieves discovered work from the specified time period
2. Groups by type, priority, and source
3. Lists Jira issues created
4. Provides statistics and trends

Can be called from standup_summary or weekly_summary skills.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("discovered_work_summary", '{
  "period": "daily",
  "include_pending": true,
  "include_synced": true,
  "format": "markdown"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Calculate the number of days to look back**
2. **Load discovered work for the period**
3. **Analyze trends in discovered work**
4. **Build markdown formatted summary**
5. **Build brief one-line summary**
6. **Log summary generation**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `period` | string | No | `daily` | Time period: 'daily' (1 day), 'weekly' (7 days), or number of days |
| `include_pending` | boolean | No | `true` | Include items not yet synced to Jira |
| `include_synced` | boolean | No | `true` | Include items already synced to Jira |
| `format` | string | No | `markdown` | Output format: 'markdown', 'slack', 'brief' |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the discovered_work_summary skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("discovered_work_summary", '{
  "period": "daily",
  "include_pending": true,
  "include_synced": true,
  "format": "markdown"
}')
```

### Via Command (if configured)

```
/discovered-work-summary
```

## MCP Tools Used

- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/discovered_work_summary.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/discovered_work_summary.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
