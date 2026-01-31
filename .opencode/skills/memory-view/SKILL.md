---
name: memory-view
description: View and manage the persistent memory system
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: memory_view.yaml
  executable: "true"
---

# memory_view

View and manage the persistent memory system.

Shows:
- Active issues you're working on
- Open MRs and their status
- Follow-up tasks
- Environment health summary
- Recent session activity

Actions:
- Clear completed items
- Add follow-up tasks
- View learned patterns

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("memory_view", '{
  "section": "all",
  "action": "example-action",
  "followup_text": "example-followup_text",
  "followup_priority": "normal",
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Search for code related to memory viewing**
2. **Parse view code search results**
3. **Load all memory files**
4. **Perform any requested action**
5. **Format memory view output**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `section` | string | No | `all` | Which section to view: - all: Everything - work: Active issues and MRs - followups: Follow-up tasks - environments: Environment health - patterns: Learned error patterns - sessions: Recent session logs  |
| `action` | string | No | `-` | Optional action to perform: - clear_completed: Remove completed items - add_followup: Add a follow-up task (requires followup_text) - clear_old_sessions: Remove sessions older than 7 days  |
| `followup_text` | string | No | `-` | Text for new follow-up task (used with action=add_followup) |
| `followup_priority` | string | No | `normal` | Priority for new follow-up: high, medium, normal |
| `slack_format` | boolean | No | `false` | Use Slack link format |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the memory_view skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("memory_view", '{
  "section": "all",
  "action": "example-action",
  "followup_text": "example-followup_text",
  "followup_priority": "normal",
  "slack_format": false
}')
```

### Via Command (if configured)

```
/memory-view
```

## MCP Tools Used

- `code_search`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/memory_view.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/memory_view.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
