---
name: check-my-prs
description: Check your open MRs for feedback from reviewers
license: MIT
compatibility: opencode
metadata:
  version: "1.2"
  source: check_my_prs.yaml
  executable: "true"
---

# check_my_prs

Check your open MRs for feedback from reviewers.

Shows:
- MRs with unaddressed feedback (need your response)
- MRs awaiting review (no feedback yet)
- MRs ready to merge (approved)

Helps you respond to reviewer comments.

Resolves project from repo_name or issue_key if not explicitly provided.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("check_my_prs", '{
  "project": "example-project",
  "repo_name": "example-repo_name",
  "show_approved": true,
  "auto_merge": false,
  "auto_rebase": false,
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab MR tools**
2. **Initialize failure tracking**
3. **Get PR best practices from knowledge**
4. **Parse PR best practices**
5. **Check for known GitLab MR issues**
6. **Determine which GitLab project to check**
7. **Get current system username**
8. **Fetch my open MRs from GitLab**
9. **Parse MR list using shared parser**
10. **Get details of first MR**
11. **Analyze feedback status of first MR using shared parser**
12. **Get detailed comments if MR needs response**
13. **Automatically rebase MR with conflicts**
14. **Compile status of all my MRs**
15. **Update summary if MR was merged**
16. **Update open MRs in memory with current status**
17. **Log PR check to session**
18. **Search for code related to my PRs**
19. **Parse PR code search results**
20. **Detect failure patterns from PR checks**
21. **Learn from GitLab VPN failures**
22. **Learn from merge conflict failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `-` | GitLab project path (resolved from repo_name if not provided) |
| `repo_name` | string | No | `-` | Repository name from config (e.g., 'automation-analytics-backend') |
| `show_approved` | boolean | No | `true` | Include approved MRs in output |
| `auto_merge` | boolean | No | `false` | Automatically merge approved MRs (asks first if false) |
| `auto_rebase` | boolean | No | `false` | Automatically rebase MRs with merge conflicts |
| `slack_format` | boolean | No | `false` | Use Slack link format in summary |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the check_my_prs skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("check_my_prs", '{
  "project": "example-project",
  "repo_name": "example-repo_name",
  "show_approved": true,
  "auto_merge": false,
  "auto_rebase": false,
  "slack_format": false
}')
```

### Via Command (if configured)

```
/check-my-prs
```

## MCP Tools Used

- `code_search`
- `gitlab_mr_list`
- `gitlab_mr_view`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/check_my_prs.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/check_my_prs.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
