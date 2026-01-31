---
name: clone-jira-issue
description: Clone a Jira issue for similar work
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: clone_jira_issue.yaml
  executable: "true"
---

# clone_jira_issue

Clone a Jira issue for similar work.

This skill:
- Clones an existing issue
- Links to the original
- Assigns to current user

Uses: jira_view_issue, jira_clone_issue, jira_add_link, jira_assign

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("clone_jira_issue", '{
  "issue_key": "example-issue_key",
  "new_summary": "example-new_summary",
  "link_type": "relates to",
  "assign_to_me": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Jira tools**
2. **Check for known Jira issues**
3. **Get source issue details**
4. **Parse source issue**
5. **Clone the issue**
6. **Parse clone result**
7. **Link clone to original**
8. **Assign to current user**
9. **Log clone action**
10. **Ensure cloned issue has proper details (uses jira_hygiene skill)**
11. **Track issue clones for patterns**
12. **Add cloned issue to active issues**
13. **Search for code related to the source issue**
14. **Parse clone code search results**
15. **Detect failure patterns from clone operations**
16. **Learn from Jira issue not found failures**
17. **Learn from Jira auth failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `issue_key` | string | Yes | `-` | Source issue key to clone (e.g., AAP-12345) |
| `new_summary` | string | No | `-` | New summary (optional, defaults to 'Clone of <original>') |
| `link_type` | string | No | `relates to` | Link type to original (relates to, blocks, is blocked by) |
| `assign_to_me` | boolean | No | `true` | Assign cloned issue to current user |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the clone_jira_issue skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("clone_jira_issue", '{
  "issue_key": "example-issue_key",
  "new_summary": "example-new_summary",
  "link_type": "relates to",
  "assign_to_me": true
}')
```

### Via Command (if configured)

```
/clone-jira-issue
```

## MCP Tools Used

- `code_search`
- `jira_add_link`
- `jira_assign`
- `jira_clone_issue`
- `jira_view_issue`
- `learn_tool_fix`
- `memory_append`
- `memory_session_log`
- `persona_load`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/clone_jira_issue.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/clone_jira_issue.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
