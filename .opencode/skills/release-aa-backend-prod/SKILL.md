---
name: release-aa-backend-prod
description: Release Automation Analytics backend to production
license: MIT
compatibility: opencode
metadata:
  version: "1.2"
  source: release_aa_backend_prod.yaml
  executable: "true"
---

# release_aa_backend_prod

Release Automation Analytics backend to production.
This skill guides you through the promotion process from stage to production
by updating the commit SHA in app-interface and creating a PR for approval.

Resolves paths and Quay images from config.json.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("release_aa_backend_prod", '{
  "commit_sha": "example-commit_sha",
  "release_date": "{{ today }}",
  "include_billing": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load release persona for Git, Quay, and app-interface tools**
2. **Initialize failure tracking**
3. **Check for known release/deployment issues**
4. **Get release-related gotchas from knowledge**
5. **Parse release-related gotchas**
6. **Load release configuration from config.json**
7. **Verify the commit SHA exists in automation-analytics-backend**
8. **Verify the container image exists in Quay.io**
9. **Read current production SHA from app-interface using shared parser**
10. **Get list of commits being released**
11. **Format changelog output**
12. **Create Jira story for tracking this release (uses create_jira_issue skill)**
13. **Load release persona for Git and app-interface tools**
14. **Check app-interface repo status**
15. **Ensure no uncommitted changes**
16. **Switch to master branch**
17. **Fetch latest from upstream**
18. **Rebase on upstream master**
19. **Check for existing release branches**
20. **Determine branch name (handle existing versions)**
21. **Create branch for this release**
22. **set_branch_name**
23. **Update production namespace ref to new SHA using shared parser**
24. **Update billing production namespace ref (if requested) using shared parser**
25. **Stage the deploy file changes**
26. **Build commit message following commit lint rules**
27. **Commit the release changes following commit lint rules**
28. **Push release branch to origin**
29. **Build MR title using config.json commit format**
30. **Load developer persona for GitLab tools**
31. **Create merge request for team approval**
32. **Add MR link to Jira issue**
33. **Notify team channel about release**
34. **Notify team channel about production release MR**
35. **Search for code related to this production release**
36. **Parse release code search results**
37. **Log release to session and track deployment**
38. **Log release to session**
39. **Track production releases for patterns**
40. **Update release state in memory**
41. **Detect failure patterns from release operations**
42. **Learn from image not found failures**
43. **Learn from GitLab VPN failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `commit_sha` | string | Yes | `-` | Full SHA1 commit to release (must exist in automation-analytics-backend repo and have image in Quay) |
| `release_date` | string | No | `{{ today }}` | Release date for Jira title (YYYY-MM-DD format, defaults to today) |
| `include_billing` | boolean | No | `false` | Also promote the billing component to production |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the release_aa_backend_prod skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("release_aa_backend_prod", '{
  "commit_sha": "example-commit_sha",
  "release_date": "{{ today }}",
  "include_billing": false
}')
```

### Via Command (if configured)

```
/release-aa-backend-prod
```

## MCP Tools Used

- `code_search`
- `git_add`
- `git_branch_list`
- `git_checkout`
- `git_commit`
- `git_fetch`
- `git_log`
- `git_push`
- `git_rebase`
- `git_status`
- `gitlab_mr_create`
- `jira_add_comment`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`
- `quay_get_tag`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/release_aa_backend_prod.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/release_aa_backend_prod.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
