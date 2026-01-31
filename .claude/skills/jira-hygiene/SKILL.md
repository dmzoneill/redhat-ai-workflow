---
name: jira-hygiene
description: Check and fix Jira issue hygiene - ensures issues have proper details,
license: MIT
compatibility: opencode
metadata:
  version: "1.2"
  source: jira_hygiene.yaml
  executable: "true"
---

# jira_hygiene

Check and fix Jira issue hygiene - ensures issues have proper details,
acceptance criteria, priority, labels, epic links, and formatting.
Transitions New issues to Refinement when complete.

Resolves project and component from issue_key prefix or repo_name.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("jira_hygiene", '{
  "issue_key": "example-issue_key",
  "repo_name": "example-repo_name",
  "auto_fix": true,
  "auto_transition": true,
  "epic_key": "example-epic_key",
  "story_points": "example-story_points",
  "priority": "example-priority"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Jira tools**
2. **Initialize failure tracking**
3. **Get Jira best practices from knowledge**
4. **Parse Jira best practices**
5. **Check for known Jira issues**
6. **Determine Jira project and default component from issue key**
7. **Fetch issue details from Jira**
8. **Parse issue fields for validation using shared parser**
9. **Check issue against hygiene rules**
10. **Determine which fixes to apply automatically**
11. **Transition issue status to Refinement**
12. **Set missing priority**
13. **Link issue to epic**
14. **Set story points**
15. **Summarize what was fixed**
16. **build_report**
17. **Search for code related to this Jira issue**
18. **Parse related code search results**
19. **Log hygiene check to session**
20. **Track hygiene checks for patterns**
21. **Track common hygiene issues for insights**
22. **Create follow-up task if issues need manual input**
23. **Detect failure patterns from hygiene checks**
24. **Learn from Jira failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `issue_key` | string | Yes | `-` | Jira issue key to check (e.g., AAP-12345) |
| `repo_name` | string | No | `-` | Repository name from config to determine component |
| `auto_fix` | boolean | No | `true` | Automatically fix issues where possible |
| `auto_transition` | boolean | No | `true` | Auto-transition New → Refinement when ready |
| `epic_key` | string | No | `-` | Epic key to link issue to (e.g., AAP-50000). If provided with auto_fix, will set epic. |
| `story_points` | integer | No | `-` | Story points to set (e.g., 3). If provided with auto_fix, will set points. |
| `priority` | string | No | `-` | Priority to set (e.g., 'Major'). If provided with auto_fix, will set priority. |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the jira_hygiene skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("jira_hygiene", '{
  "issue_key": "example-issue_key",
  "repo_name": "example-repo_name",
  "auto_fix": true,
  "auto_transition": true,
  "epic_key": "example-epic_key",
  "story_points": "example-story_points",
  "priority": "example-priority"
}')
```

### Via Command (if configured)

```
/jira-hygiene
```

## MCP Tools Used

- `code_search`
- `jira_set_epic`
- `jira_set_priority`
- `jira_set_status`
- `jira_set_story_points`
- `jira_view_issue_json`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/jira_hygiene.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/jira_hygiene.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
