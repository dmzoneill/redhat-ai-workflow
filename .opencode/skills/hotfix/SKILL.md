---
name: hotfix
description: Create a hotfix by cherry-picking a commit to a release branch
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: hotfix.yaml
  executable: "true"
---

# hotfix

Create a hotfix by cherry-picking a commit to a release branch.

Use when:
- A bug fix needs to be backported to an older release
- You need to create a patch release quickly
- A fix on main needs to go to a release branch

The skill will:
1. Fetch latest from remote
2. Checkout the target release branch
3. Cherry-pick the specified commit(s)
4. Optionally create a release tag
5. Push to remote

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("hotfix", '{
  "commit": "example-commit",
  "target_branch": "example-target_branch",
  "repo": "example-repo",
  "tag": "example-tag",
  "push": false,
  "jira_key": "example-jira_key",
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Git and Jira tools**
2. **Initialize auto-heal tracking**
3. **Check for known hotfix issues before starting**
4. **Load previous hotfix history for patterns**
5. **Get release/deployment gotchas from knowledge**
6. **Parse release-related gotchas**
7. **Determine repository path**
8. **Fetch latest from remote**
9. **List available branches**
10. **Verify target branch exists**
11. **Checkout the target release branch**
12. **Parse checkout result**
13. **Show what the commit changes**
14. **Parse commit diff**
15. **Show blame for first changed file**
16. **Parse blame output**
17. **Find code related to the hotfix for impact analysis**
18. **Parse related code for impact assessment**
19. **Cherry-pick the commit**
20. **Parse cherry-pick result**
21. **Create release tag**
22. **Parse tag result**
23. **Push changes and tag to remote**
24. **Parse push result**
25. **Link Jira issue if provided**
26. **Log hotfix to session**
27. **Notify team channel about hotfix creation**
28. **Learn from this hotfix for future reference**
29. **Track conflict patterns for auto-remediation hints**
30. **Update environment state after hotfix**
31. **Detect failure patterns from hotfix operations**
32. **Learn from cherry-pick conflict failures**
33. **Learn from push rejected failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `commit` | string | Yes | `-` | Commit SHA to cherry-pick (from main branch) |
| `target_branch` | string | Yes | `-` | Target release branch (e.g., 'release/1.2', 'v1.2-branch') |
| `repo` | string | No | `-` | Repository path (defaults to cwd) |
| `tag` | string | No | `-` | Optional: create a release tag (e.g., 'v1.2.3') |
| `push` | boolean | No | `false` | Push changes to remote after cherry-pick |
| `jira_key` | string | No | `-` | Jira issue key for the hotfix |
| `slack_format` | boolean | No | `false` | Use Slack link format in report |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the hotfix skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("hotfix", '{
  "commit": "example-commit",
  "target_branch": "example-target_branch",
  "repo": "example-repo",
  "tag": "example-tag",
  "push": false,
  "jira_key": "example-jira_key",
  "slack_format": false
}')
```

### Via Command (if configured)

```
/hotfix
```

## MCP Tools Used

- `code_search`
- `git_blame`
- `git_branch_list`
- `git_checkout`
- `git_cherry_pick`
- `git_diff`
- `git_fetch`
- `git_push`
- `git_tag`
- `jira_add_comment`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/hotfix.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/hotfix.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
