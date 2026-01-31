---
name: sprint-autopilot
description: Work on a sprint issue with dynamic persona switching
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: sprint_autopilot.yaml
  executable: "true"
---

# sprint_autopilot

Work on a sprint issue with dynamic persona switching.
Different stages load different personas for their required tools.

Stages:
1. Issue Analysis (developer) - Analyze requirements, check clarity
2. Branch Setup (developer) - Create feature branch via start_work
3. Code Research (developer) - Search codebase for relevant patterns
4. Implementation (in Cursor chat) - Human/Claude does actual coding
5. MR Creation (developer) - Create merge request
6. Deployment Check (devops) - Optional ephemeral deployment
7. Finalize (developer) - Update Jira, log timeline

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("sprint_autopilot", '{
  "issue_key": "example-issue_key",
  "repo_path": ".",
  "needs_deployment_check": false,
  "auto_stash": true,
  "skip_clarity_check": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for issue analysis**
2. **Check git status for uncommitted changes**
3. **Evaluate if worktree is safe to proceed**
4. **Abort if worktree is in unsafe state**
5. **Stash uncommitted changes if present**
6. **Fetch issue details from Jira**
7. **Check if issue has enough detail to work on**
8. **Ask for clarification if issue is unclear**
9. **Mark issue as waiting for clarification**
10. **Create feature branch and set up for work**
11. **Extract branch name from start_work result**
12. **Search codebase for relevant patterns**
13. **Load project-specific patterns and gotchas**
14. **Prepare context for implementation**
15. **Log that issue is ready for implementation**
16. **Check if there are changes to commit**
17. **Determine if there are changes to create MR for**
18. **Create merge request for the changes**
19. **Extract MR URL and ID from result**
20. **Switch to devops persona for deployment**
21. **Deploy to ephemeral for testing**
22. **Switch back to developer persona**
23. **Add MR link to Jira issue**
24. **Log MR creation to timeline**
25. **Prepare final summary**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `issue_key` | string | Yes | `-` | Jira issue key (e.g., AAP-12345) |
| `repo_path` | string | No | `.` | Path to the repository |
| `needs_deployment_check` | string | No | `false` | Whether to deploy to ephemeral for testing |
| `auto_stash` | string | No | `true` | Automatically stash uncommitted changes |
| `skip_clarity_check` | string | No | `false` | Skip the issue clarity check |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the sprint_autopilot skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("sprint_autopilot", '{
  "issue_key": "example-issue_key",
  "repo_path": ".",
  "needs_deployment_check": false,
  "auto_stash": true,
  "skip_clarity_check": false
}')
```

### Via Command (if configured)

```
/sprint-autopilot
```

## MCP Tools Used

- `code_search`
- `git_stash`
- `git_status`
- `jira_add_comment`
- `jira_view_issue`
- `knowledge_query`
- `memory_append`
- `persona_load`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/sprint_autopilot.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/sprint_autopilot.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
