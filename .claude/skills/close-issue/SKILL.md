---
name: close-issue
description: Close a Jira issue by transitioning it to Done
license: MIT
compatibility: opencode
metadata:
  version: "1.2"
  source: close_issue.yaml
  executable: "true"
---

# close_issue

Close a Jira issue by transitioning it to Done.
Adds a comment summarizing the work from branch commits.

Resolves Jira statuses from config.json.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("close_issue", '{
  "issue_key": "example-issue_key",
  "repo": ".",
  "add_comment": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Git, GitLab, and Jira tools**
2. **Get Jira workflow patterns from knowledge base**
3. **Parse Jira knowledge for workflow context**
4. **Check for known Jira issues before starting**
5. **Load Jira status configuration**
6. **Initialize failure tracking**
7. **Fetch current issue details**
8. **check_status**
9. **List all git branches**
10. **Find branch matching this issue using shared parser**
11. **Get commits from the issue branch**
12. **Parse commit log**
13. **Check for associated Merge Request**
14. **Search for code related to this issue**
15. **Parse related code search results**
16. **parse_mr**
17. **build_comment**
18. **Add closing comment to Jira**
19. **Check what transitions are available from current status**
20. **Select the transition to Done using shared parser**
21. **Execute the transition**
22. **Verify issue status after transition**
23. **Notify team channel about closed issue**
24. **Notify team channel about issue closure**
25. **Build timestamp for memory**
26. **Log issue closure to session log**
27. **Remove issue from active_issues in memory**
28. **Learn from issue closure for future reference**
29. **Save closure context for other skills**
30. **Detect failure patterns from close operations**
31. **Learn from transition failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `issue_key` | string | Yes | `-` | Jira issue key (e.g., AAP-12345) |
| `repo` | string | No | `.` | Repository path to look for branch/commits |
| `add_comment` | boolean | No | `true` | Whether to add a closing comment with commit summary |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the close_issue skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("close_issue", '{
  "issue_key": "example-issue_key",
  "repo": ".",
  "add_comment": true
}')
```

### Via Command (if configured)

```
/close-issue
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `git_branch_list`
- `git_log`
- `gitlab_list_mrs`
- `jira_add_comment`
- `jira_get_issue`
- `jira_get_transitions`
- `jira_transition_issue`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/close_issue.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/close_issue.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
