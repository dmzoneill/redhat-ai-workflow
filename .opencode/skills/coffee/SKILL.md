---
name: coffee
description: Morning briefing - everything you need to know at the start of your work day
license: MIT
compatibility: opencode
metadata:
  version: "2.0"
  source: coffee.yaml
  executable: "true"
---

# coffee

Morning briefing - everything you need to know at the start of your work day.

This skill gathers and summarizes:
- 📅 Calendar: Today's meetings with Meet links
- 📧 Email: Unread emails categorized (people vs newsletters)
- 🔀 PRs: Your open PRs, feedback waiting, failed pipelines
- 👀 Reviews: PRs assigned to you for review
- 📋 Jira: Sprint activity for last day/week
- 🚀 Merges: Recent merged code in aa-backend
- 🧪 Ephemeral: Your active test environments with expiry
- 📝 Yesterday: Your commits (for standup prep)
- 🚨 Alerts: Any firing or recent alerts
- 🎯 Actions: Suggested next steps
- **NEW:** 🧠 Knowledge: Project knowledge stats and index freshness
- **NEW:** 🔍 Vector Search: Index health and search stats

Requires: Gmail API access (same OAuth as Calendar)

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("coffee", '{
  "full_email_scan": false,
  "auto_archive_email": false,
  "days_back": 1,
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab, Git, and Jira tools**
2. **Load configuration using shared loader**
3. **Load current work state from memory**
4. **Load yesterday's session log for context**
5. **Check for known GitLab tool issues**
6. **Check for known Jira tool issues**
7. **Check for known Bonfire tool issues**
8. **Aggregate all known issues**
9. **Get vector index statistics**
10. **Parse vector index stats**
11. **Get knowledge base statistics**
12. **Parse knowledge stats**
13. **Fetch today's calendar events**
14. **Fetch, analyze, and optionally triage unread emails**
15. **Extract all GitLab projects from config for multi-project queries**
16. **Get PRs authored by me in automation-analytics-backend**
17. **Get PRs authored by me in pdf-generator**
18. **Get PRs authored by me in app-interface**
19. **Get PRs authored by me in konflux-release-data**
20. **Parse and aggregate MR lists from all projects, detect network errors**
21. **Extract MR IDs and their projects for feedback check**
22. **Get comments for first PR**
23. **Get comments for second PR**
24. **Get comments for third PR**
25. **Parse all PR comments for feedback**
26. **Build JQL query with proper days_back value**
27. **Get Jira activity for the sprint**
28. **Parse Jira search results**
29. **Get recently merged MRs in project 1**
30. **Get recently merged MRs in project 2**
31. **Parse and aggregate merged MRs from all projects**
32. **Load incident persona for Alertmanager tools**
33. **Check for Automation Analytics alerts in stage**
34. **Check for Automation Analytics alerts in production**
35. **Parse alert results**
36. **Parse .gitlab-ci.yml to find jobs that allow failure**
37. **Extract branch names from MRs for CI status check**
38. **Get CI status for first MR**
39. **Get CI status for second MR**
40. **Get CI status for third MR**
41. **Parse CI status for failed pipelines, excluding allow_failure jobs**
42. **Load devops persona for Bonfire tools**
43. **List your active ephemeral environments**
44. **Parse namespace list**
45. **Load developer persona for Git and GitLab tools**
46. **Get your commits from yesterday (for standup)**
47. **Parse commit output**
48. **Get PRs where you're assigned as reviewer in project 1**
49. **Get PRs where you're assigned as reviewer in project 2**
50. **Parse and aggregate review request lists from all projects**
51. **Create the morning briefing**
52. **Log morning briefing to session**
53. **Sync memory with actual PR/issue state**
54. **Learn from pipeline failures for future reference**
55. **Save context for other skills to use**
56. **Learn from network/VPN failures if detected**
57. **Learn from Jira failures if detected**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `full_email_scan` | boolean | No | `false` | Process all unread emails (vs just summary) |
| `auto_archive_email` | boolean | No | `false` | Automatically archive processed emails |
| `days_back` | integer | No | `1` | Days to look back for activity (default: 1) |
| `slack_format` | boolean | No | `false` | Use Slack's <URL|Text> link format instead of standard markdown |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the coffee skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("coffee", '{
  "full_email_scan": false,
  "auto_archive_email": false,
  "days_back": 1,
  "slack_format": false
}')
```

### Via Command (if configured)

```
/coffee
```

## MCP Tools Used

- `alertmanager_alerts`
- `bonfire_namespace_list`
- `check_known_issues`
- `git_log`
- `gitlab_ci_status`
- `gitlab_mr_comments`
- `gitlab_mr_list`
- `jira_search`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/coffee.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/coffee.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
