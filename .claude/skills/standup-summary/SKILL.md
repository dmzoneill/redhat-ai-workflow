---
name: standup-summary
description: Generate a standup summary from recent activity:
license: MIT
compatibility: opencode
metadata:
  version: "1.1"
  source: standup_summary.yaml
  executable: "true"
---

# standup_summary

Generate a standup summary from recent activity:
- Git commits from yesterday/today
- Jira issues worked on (In Progress, In Review)
- MRs created/reviewed
- Issues closed

If 'repo' is not provided, can be resolved from 'repo_name' or 'issue_key' via config.

Perfect for daily standups or status updates.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("standup_summary", '{
  "repo": "example-repo",
  "repo_name": "example-repo_name",
  "issue_key": "example-issue_key",
  "days": 1,
  "include_jira": true,
  "include_gitlab": true,
  "author": "example-author",
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab, Jira, and Git tools**
2. **Check for known GitLab issues before starting**
3. **Check for known Jira issues before starting**
4. **Initialize failure tracking**
5. **Determine which repo and GitLab project to use**
6. **Get git author email**
7. **Get git author name**
8. **Parse author info**
9. **Get recent commits**
10. **Parse commit log for standup**
11. **Load meetings persona for Google Calendar tools**
12. **Get today's calendar events**
13. **Parse calendar events**
14. **Load slack persona for Slack channel reading**
15. **Find team channel ID**
16. **Get recent Slack mentions**
17. **Parse Slack messages**
18. **Get all my assigned issues (quick query)**
19. **Get my issues in progress**
20. **Get recently closed issues**
21. **Parse Jira issues using shared parser**
22. **Get MRs I created**
23. **Get MRs I reviewed**
24. **Parse GitLab MR activity using shared parser**
25. **Build standup summary**
26. **Get project knowledge confidence score**
27. **Parse knowledge metadata**
28. **Get vector index statistics**
29. **Parse vector stats**
30. **Load current work state from memory**
31. **Enhance standup with memory context**
32. **Get discovered work from the last day**
33. **Add discovered work section to standup**
34. **Finalize standup output**
35. **Log standup generation to session**
36. **Learn from this standup for activity tracking**
37. **Track which issues are actively being worked on**
38. **Save standup context for other skills**
39. **Search for code related to recent commits**
40. **Parse recent code search results**
41. **Detect failure patterns from standup data gathering**
42. **Learn from GitLab VPN failures**
43. **Learn from Jira timeout failures**
44. **Log standup generation to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `repo` | string | No | `-` | Repository path - if not provided, resolved from repo_name or issue_key |
| `repo_name` | string | No | `-` | Repository name from config (e.g., 'automation-analytics-backend') |
| `issue_key` | string | No | `-` | Jira issue key - used to resolve repo and Jira project |
| `days` | integer | No | `1` | How many days back to look (default: 1 for yesterday) |
| `include_jira` | boolean | No | `true` | Include Jira issues |
| `include_gitlab` | boolean | No | `true` | Include GitLab MR activity |
| `author` | string | No | `-` | Git author email (defaults to git config) |
| `slack_format` | boolean | No | `false` | Use Slack link format in summary |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the standup_summary skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("standup_summary", '{
  "repo": "example-repo",
  "repo_name": "example-repo_name",
  "issue_key": "example-issue_key",
  "days": 1,
  "include_jira": true,
  "include_gitlab": true,
  "author": "example-author",
  "slack_format": false
}')
```

### Via Command (if configured)

```
/standup-summary
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `code_stats`
- `git_config_get`
- `git_log`
- `gitlab_mr_list`
- `google_calendar_list_events`
- `jira_my_issues`
- `jira_search`
- `knowledge_query`
- `learn_tool_fix`
- `memory_read`
- `memory_session_log`
- `persona_load`
- `slack_find_channel`
- `slack_list_messages`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/standup_summary.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/standup_summary.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
