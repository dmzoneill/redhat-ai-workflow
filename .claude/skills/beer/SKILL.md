---
name: beer
description: End of day wrap-up - review what you accomplished and prep for tomorrow
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: beer.yaml
  executable: "true"
---

# beer

End of day wrap-up - review what you accomplished and prep for tomorrow.

This skill gathers and summarizes:
- ✅ Wins: Commits pushed, PRs merged, issues closed
- 📊 Stats: Lines changed, files touched
- 🔄 WIP: Uncommitted changes, draft PRs
- ⏰ Tomorrow: Early meetings, deadlines
- 🧹 Cleanup: Stale branches, expiring ephemeral envs
- 📝 Standup: Auto-generated standup notes
- 🎯 Follow-ups: PRs needing attention tomorrow

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("beer", '{
  "generate_standup": true,
  "cleanup_prompts": true,
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab, Git, and Jira tools**
2. **Search for code related to end of day activities**
3. **Parse EOD code search results**
4. **Get project patterns and learnings from knowledge base**
5. **Parse project knowledge for wrap-up context**
6. **Check for known GitLab issues before starting**
7. **Check for known Google Calendar issues before starting**
8. **Load configuration using shared loader**
9. **Load current work state from memory**
10. **Get commits you pushed today**
11. **Parse today's commits**
12. **Check for uncommitted work**
13. **Check backend repo for uncommitted changes**
14. **Check workflow repo for uncommitted changes**
15. **Parse uncommitted changes from both repos**
16. **Get PRs merged today**
17. **Filter for today's merges only**
18. **Get my open PRs**
19. **Parse my open PRs using shared parser**
20. **Fetch tomorrow's calendar events**
21. **Load devops persona for Bonfire tools**
22. **Check ephemeral namespaces for cleanup**
23. **Parse ephemeral namespaces**
24. **Get branches merged into main**
25. **Extract stale branches (merged but not main/master)**
26. **Generate standup notes for tomorrow**
27. **Get commits from the past week**
28. **Get line change stats for the week**
29. **Parse weekly activity stats**
30. **Create the end of day wrap-up**
31. **Log end of day wrap-up to session**
32. **Sync memory with actual work state at end of day**
33. **Learn from daily activity patterns**
34. **Save standup notes for tomorrow morning**
35. **Detect failure patterns from EOD data gathering**
36. **Learn from GitLab VPN failures**
37. **Learn from Google Calendar OAuth failures**
38. **Learn from bonfire VPN failures**
39. **Log EOD wrap-up to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `generate_standup` | boolean | No | `true` | Generate standup notes for tomorrow |
| `cleanup_prompts` | boolean | No | `true` | Show cleanup reminders (branches, ephemeral) |
| `slack_format` | boolean | No | `false` | Use Slack link format |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the beer skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("beer", '{
  "generate_standup": true,
  "cleanup_prompts": true,
  "slack_format": false
}')
```

### Via Command (if configured)

```
/beer
```

## MCP Tools Used

- `bonfire_namespace_list`
- `check_known_issues`
- `code_search`
- `git_branch_list`
- `git_log`
- `git_status`
- `gitlab_mr_list`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/beer.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/beer.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
