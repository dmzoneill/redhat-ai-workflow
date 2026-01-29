# 📋 discovered_work_summary

> Generate summaries of discovered work for daily standups or weekly reports

## Overview

The `discovered_work_summary` skill generates summaries of work items discovered during other skill executions. When you run skills like `review_pr`, `start_work`, or `investigate_alert`, they often uncover additional work (tech debt, bugs, improvements) that gets logged for later. This skill retrieves and summarizes that discovered work.

It can be called standalone or integrated into other reporting skills like `standup_summary` or `weekly_summary`.

## Quick Start

```text
skill_run("discovered_work_summary", '{}')
```

Or specify a time period:

```text
skill_run("discovered_work_summary", '{"period": "weekly"}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `period` | string | No | `"daily"` | Time period: `"daily"` (1 day), `"weekly"` (7 days), or number of days |
| `include_pending` | boolean | No | `true` | Include items not yet synced to Jira |
| `include_synced` | boolean | No | `true` | Include items already synced to Jira |
| `format` | string | No | `"markdown"` | Output format: `"markdown"`, `"slack"`, or `"brief"` |

## What It Does

1. **Calculates Period** - Determines how many days to look back based on input
2. **Loads Period Data** - Retrieves discovered work items from memory for the specified period
3. **Analyzes Trends** - Calculates statistics like daily average, most common type, sync rate
4. **Builds Summary** - Generates formatted output based on requested format:
   - Quick stats (discovered, synced, pending)
   - Jira issues created
   - Breakdown by type
   - Breakdown by day (for weekly)
   - Pending items list
   - Insights and recommendations

## Work Types

| Type | Description |
|------|-------------|
| `tech_debt` | Technical debt to address |
| `bug` | Bugs found during other work |
| `improvement` | Enhancement opportunities |
| `missing_test` | Test coverage gaps |
| `missing_docs` | Documentation gaps |
| `security` | Security concerns |
| `discovered_work` | General discovered items |

## Example Usage

### Daily Summary

```python
skill_run("discovered_work_summary", '{"period": "daily"}')
```

### Weekly Summary

```python
skill_run("discovered_work_summary", '{"period": "weekly"}')
```

### Custom Days with Slack Format

```python
skill_run("discovered_work_summary", '{"period": "14", "format": "slack"}')
```

### Brief One-Line Summary

```python
skill_run("discovered_work_summary", '{"format": "brief"}')
```

## Example Output

```text
## 📋 Discovered Work Summary (7 days)
*Generated: 2026-01-26 10:30*

### 📊 Quick Stats
- **Discovered:** 12 items
- **Synced to Jira:** 8 items (67%)
- **Pending backlog:** 4 items
- **Daily average:** 1.7 items/day

### 🎫 Jira Issues Created
- [AAP-61234](https://issues.redhat.com/browse/AAP-61234)
- [AAP-61235](https://issues.redhat.com/browse/AAP-61235)
- [AAP-61236](https://issues.redhat.com/browse/AAP-61236)

### 📁 By Type
- 🔧 **tech_debt:** 5
- 🐛 **bug:** 3
- ✨ **improvement:** 2
- 🧪 **missing_test:** 2

### 📅 By Day
- `2026-01-20`: ██ (2)
- `2026-01-21`: █ (1)
- `2026-01-22`: ███ (3)
- `2026-01-23`: ██ (2)
- `2026-01-24`: ██ (2)
- `2026-01-25`: █ (1)
- `2026-01-26`: █ (1)

### ⏳ Pending (Not Yet in Jira)
- 🟡 Add retry logic to API client
- 🟡 Update deprecated dependency
- 🟢 Improve error messages
- 🟢 Add integration test for billing

*Run `skill_run("sync_discovered_work", '{"auto_create": true}')` to create Jira issues.*

### 💡 Insights
- Most common type: **tech_debt**
- Busiest day: **2026-01-22**
```

## MCP Tools Used

- `memory_session_log` - Log summary generation

## Related Skills

- [sync_discovered_work](./sync_discovered_work.md) - Create Jira issues for pending items
- [standup_summary](./standup_summary.md) - Daily standup notes
- [weekly_summary](./weekly_summary.md) - Weekly work summary
- [coffee](./coffee.md) - Morning briefing
