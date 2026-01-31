---
name: review-all-prs
description: Review all open MRs in a project
license: MIT
compatibility: opencode
metadata:
  version: "1.3"
  source: review_all_prs.yaml
  executable: "true"
---

# review_all_prs

Review all open MRs in a project.

Resolves project from repo_name or current directory if not explicitly provided.

Automatically excludes your own MRs (detected from system username).

For each MR (authored by others):
- If I gave feedback and author addressed it → approve
- If I gave feedback and author didn't respond → skip
- If I gave feedback and author responded but issues remain → more feedback
- If no previous review from me → run full review

Also shows your own MRs that have feedback from others.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("review_all_prs", '{
  "project": "example-project",
  "repo_name": "example-repo_name",
  "reviewer": "example-reviewer",
  "limit": 10,
  "dry_run": false,
  "include_my_mrs": true,
  "auto_rebase": true,
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab tools**
2. **Check for known GitLab issues before starting**
3. **Initialize failure tracking**
4. **Get code review patterns from knowledge**
5. **Parse code review patterns**
6. **Get project gotchas for review context**
7. **Parse review-relevant gotchas**
8. **Determine which GitLab project to check**
9. **Get current system username to exclude own MRs**
10. **Fetch all open MRs from GitLab**
11. **Extract MR IDs, separate own MRs from others to review using shared parsers**
12. **Extract my first MR info for subsequent tool calls**
13. **Check if any of my MRs have merge conflicts**
14. **Check for merge conflicts or needs rebase using shared parser**
15. **Automatically rebase my MR if it has conflicts**
16. **Analyze each MR for review status**
17. **Determine review status for each MR**
18. **Extract first MR info for subsequent tool calls**
19. **Get comments for MRs to check review status**
20. **Check if first MR needs action using shared parsers**
21. **Run full review for MR that needs it**
22. **Restore developer persona for GitLab approve/comment tools**
23. **Approve MR where author addressed feedback**
24. **Post follow-up comment for unresolved issues**
25. **Compile batch review results**
26. **Notify team channel about batch review**
27. **Build context for memory updates**
28. **Log batch review to session**
29. **Update teammate preferences with review counts**
30. **Search for code related to MRs being reviewed**
31. **Parse review code search results**
32. **Detect failure patterns from batch PR review**
33. **Learn from GitLab VPN failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `-` | GitLab project path (resolved from repo_name if not provided) |
| `repo_name` | string | No | `-` | Repository name from config (e.g., 'automation-analytics-backend') |
| `reviewer` | string | No | `-` | Filter by reviewer username (leave empty for all open MRs) |
| `limit` | integer | No | `10` | Maximum number of MRs to process |
| `dry_run` | boolean | No | `false` | If true, show what would happen without taking action |
| `include_my_mrs` | boolean | No | `true` | Show my own MRs that have feedback to respond to |
| `auto_rebase` | boolean | No | `true` | Automatically rebase my MRs that have merge conflicts |
| `slack_format` | boolean | No | `false` | Use Slack link format in summary |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the review_all_prs skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("review_all_prs", '{
  "project": "example-project",
  "repo_name": "example-repo_name",
  "reviewer": "example-reviewer",
  "limit": 10,
  "dry_run": false,
  "include_my_mrs": true,
  "auto_rebase": true,
  "slack_format": false
}')
```

### Via Command (if configured)

```
/review-all-prs
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `gitlab_mr_approve`
- `gitlab_mr_comment`
- `gitlab_mr_list`
- `gitlab_mr_view`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/review_all_prs.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/review_all_prs.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
