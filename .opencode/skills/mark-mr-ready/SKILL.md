---
name: mark-mr-ready
description: Mark a draft merge request as ready for review
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: mark_mr_ready.yaml
  executable: "true"
---

# mark_mr_ready

Mark a draft merge request as ready for review.
- Removes draft status from the MR
- Posts to team Slack channel asking for review
- Optionally updates Jira status to "In Review"

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("mark_mr_ready", '{
  "mr_id": "example-mr_id",
  "project": "automation-analytics/automation-analytics-backend",
  "issue_key": "example-issue_key",
  "update_jira": true,
  "run_linting": true,
  "repo": "example-repo",
  "check_docs": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab, Git, and Jira tools**
2. **Get MR readiness patterns from knowledge base**
3. **Parse MR readiness knowledge**
4. **Check for known GitLab issues before starting**
5. **Initialize failure tracking**
6. **load_config**
7. **Get current MR details**
8. **parse_mr**
9. **Resolve repo path for linting**
10. **Check code formatting before marking ready**
11. **Run flake8 linting before marking ready**
12. **Parse lint results**
13. **Block marking ready if lint fails**
14. **Check documentation before marking ready**
15. **Parse documentation check results**
16. **Remove draft status from MR**
17. **Build Slack message with proper team mention**
18. **Notify team about MR ready for review (uses notify_mr skill)**
19. **Restore developer persona for Jira tools**
20. **Move Jira to In Review**
21. **Search for code related to the MR being marked ready**
22. **Parse MR code search results**
23. **Build timestamp for memory**
24. **Log MR ready to session log**
25. **Update MR status in memory to needs_review**
26. **Track MR ready actions for patterns**
27. **Update open MRs state with ready status**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mr_id` | string | Yes | `-` | MR ID (e.g., '1459' or '!1459') |
| `project` | string | No | `automation-analytics/automation-analytics-backend` | GitLab project path |
| `issue_key` | string | No | `-` | Jira issue key to update status (e.g., AAP-12345) |
| `update_jira` | boolean | No | `true` | Update Jira status to In Review |
| `run_linting` | boolean | No | `true` | Run linting checks before marking MR ready |
| `repo` | string | No | `-` | Repository path for linting (auto-detected if not provided) |
| `check_docs` | boolean | No | `true` | Check documentation before marking ready (if docs.check_on_mr=true in config) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the mark_mr_ready skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("mark_mr_ready", '{
  "mr_id": "example-mr_id",
  "project": "automation-analytics/automation-analytics-backend",
  "issue_key": "example-issue_key",
  "update_jira": true,
  "run_linting": true,
  "repo": "example-repo",
  "check_docs": true
}')
```

### Via Command (if configured)

```
/mark-mr-ready
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `git_format`
- `git_lint`
- `gitlab_mr_update`
- `gitlab_mr_view`
- `jira_set_status`
- `knowledge_query`
- `memory_session_log`
- `memory_update`
- `persona_load`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/mark_mr_ready.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/mark_mr_ready.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
