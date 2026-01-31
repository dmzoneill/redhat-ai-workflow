---
name: pr-jira-audit
description: Audit open MRs/PRs for missing Jira issue references
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: pr_jira_audit.yaml
  executable: "true"
---

# pr_jira_audit

Audit open MRs/PRs for missing Jira issue references.

Scans each open MR in the project and checks:
- MR title for Jira issue key (e.g., AAP-12345)
- MR description/body for Jira issue key
- Git commit messages for Jira issue key

For MRs without a linked Jira issue:
- Reports the missing link
- Optionally creates a new Jira issue for the MR
- Optionally adds the issue key as a comment on the MR

Use for:
- Sprint hygiene audits
- Ensuring all work is tracked in Jira
- Compliance/traceability requirements

Resolves project from repo_name or current directory if not explicitly provided.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("pr_jira_audit", '{
  "project": "example-project",
  "repo_name": "automation-analytics-backend",
  "jira_project": "AAP",
  "limit": 20,
  "auto_create": false,
  "add_comment": false,
  "dry_run": true,
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab and Jira tools**
2. **Initialize failure tracking**
3. **Determine which GitLab project to audit**
4. **Fetch all open MRs from GitLab**
5. **Parse MR list to extract IDs and titles**
6. **Extract first MR info for detailed check**
7. **Get full details of first MR including description**
8. **Get commits for first MR to check for Jira refs**
9. **Check first MR for Jira issue reference**
10. **Quick audit of all MRs based on title pattern**
11. **Prepare first missing MR for Jira creation**
12. **Create Jira issue for first MR without one (uses create_jira_issue skill)**
13. **Parse created issue result**
14. **Add comment to MR with created Jira issue**
15. **Compile audit results**
16. **Log audit to session**
17. **Track audit results for patterns**
18. **Detect failure patterns from audit**
19. **Learn from GitLab VPN failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `-` | GitLab project path (resolved from repo_name if not provided) |
| `repo_name` | string | No | `automation-analytics-backend` | Repository name from config |
| `jira_project` | string | No | `AAP` | Jira project key for creating new issues |
| `limit` | integer | No | `20` | Maximum number of MRs to audit |
| `auto_create` | boolean | No | `false` | Automatically create Jira issues for MRs without one |
| `add_comment` | boolean | No | `false` | Add a comment to the MR with the created Jira issue key |
| `dry_run` | boolean | No | `true` | If true, report what would be done without taking action |
| `slack_format` | boolean | No | `false` | Use Slack link format in summary |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the pr_jira_audit skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("pr_jira_audit", '{
  "project": "example-project",
  "repo_name": "automation-analytics-backend",
  "jira_project": "AAP",
  "limit": 20,
  "auto_create": false,
  "add_comment": false,
  "dry_run": true,
  "slack_format": false
}')
```

### Via Command (if configured)

```
/pr-jira-audit
```

## MCP Tools Used

- `gitlab_mr_comment`
- `gitlab_mr_commits`
- `gitlab_mr_list`
- `gitlab_mr_view`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/pr_jira_audit.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/pr_jira_audit.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
