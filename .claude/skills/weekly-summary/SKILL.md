---
name: weekly-summary
description: Generate a summary of work from session logs
license: MIT
compatibility: opencode
metadata:
  version: "2.0"
  source: weekly_summary.yaml
  executable: "true"
---

# weekly_summary

Generate a summary of work from session logs.

Aggregates session logs from the past week (or specified period)
and provides a summary of:
- Issues worked on
- MRs created/reviewed
- Deployments and debugging sessions
- Patterns learned
- **NEW:** Knowledge growth metrics
- **NEW:** Vector search usage stats
- **NEW:** Learned patterns summary

Useful for weekly reports or sprint reviews.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("weekly_summary", '{
  "days": 7,
  "format": "markdown",
  "repo": "automation-analytics-backend",
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab, Jira, and Git tools**
2. **Check for known GitLab issues before starting**
3. **Check for known Jira issues before starting**
4. **Initialize failure tracking**
5. **Get commits from the past week**
6. **Get my recently updated Jira issues**
7. **Get my recent merge requests**
8. **Load release persona for Konflux and Quay tools**
9. **Get recent Konflux releases**
10. **Get recent image tags from Quay**
11. **Load slack persona for Slack search**
12. **Search Slack for relevant team discussions**
13. **Parse Slack discussions**
14. **Read session logs from memory directory**
15. **Load current work state**
16. **Load learned patterns from memory**
17. **Load tool fixes from memory**
18. **Get knowledge base statistics**
19. **Get vector index statistics**
20. **Parse learning and knowledge metrics**
21. **Parse data from git, jira, gitlab, konflux**
22. **Analyze session logs for summary**
23. **Format summary for output**
24. **Search for code related to weekly activity**
25. **Parse weekly code search results**
26. **Detect failure patterns from weekly summary data gathering**
27. **Learn from GitLab VPN failures**
28. **Learn from Konflux VPN failures**
29. **Log weekly summary generation to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `days` | integer | No | `7` | Number of days to look back (default: 7) |
| `format` | string | No | `markdown` | Output format: 'markdown' or 'slack' |
| `repo` | string | No | `automation-analytics-backend` | Repository to get commit history from |
| `slack_format` | boolean | No | `false` | Use Slack link format |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the weekly_summary skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("weekly_summary", '{
  "days": 7,
  "format": "markdown",
  "repo": "automation-analytics-backend",
  "slack_format": false
}')
```

### Via Command (if configured)

```
/weekly-summary
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `code_stats`
- `git_log`
- `gitlab_mr_list`
- `jira_my_issues`
- `knowledge_query`
- `konflux_list_releases`
- `learn_tool_fix`
- `memory_read`
- `memory_session_log`
- `persona_load`
- `quay_list_aa_tags`
- `slack_search_messages`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/weekly_summary.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/weekly_summary.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
