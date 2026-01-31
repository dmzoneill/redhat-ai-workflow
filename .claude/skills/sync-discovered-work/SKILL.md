---
name: sync-discovered-work
description: Review and sync discovered work items to Jira
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: sync_discovered_work.yaml
  executable: "true"
---

# sync_discovered_work

Review and sync discovered work items to Jira.

During skill execution (review_pr, start_work, investigate_alert, etc.),
work items are discovered that need follow-up but aren't part of the
current task. This skill:

1. Lists all pending discovered work items
2. Groups them by type and priority
3. Creates Jira issues for selected items
4. Updates memory to mark items as synced

Work types:
- tech_debt: Technical debt to address
- bug: Bugs found during other work
- improvement: Enhancement opportunities
- missing_test: Test coverage gaps
- security: Security concerns
- discovered_work: General discovered items

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("sync_discovered_work", '{
  "auto_create": false,
  "priority_filter": "example-priority_filter",
  "type_filter": "example-type_filter",
  "parent_epic": "example-parent_epic",
  "dry_run": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Jira tools**
2. **Load all discovered work from memory**
3. **Check if there's any pending work**
4. **Apply priority and type filters**
5. **Build summary for user review**
6. **List all pending items for review**
7. **Prepare Jira issue data for creation (with deduplication)**
8. **Create first Jira issue**
9. **Mark first item as synced**
10. **Create second Jira issue**
11. **Mark second item as synced**
12. **Create third Jira issue**
13. **Mark third item as synced**
14. **Collect all creation results**
15. **Log sync action to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `auto_create` | boolean | No | `false` | Automatically create Jira issues for all pending items (default: false, review first) |
| `priority_filter` | string | No | `-` | Only sync items with this priority or higher (low, medium, high, critical) |
| `type_filter` | string | No | `-` | Only sync items of this type (tech_debt, bug, improvement, etc.) |
| `parent_epic` | string | No | `-` | Epic key to link all created issues to (e.g., AAP-50000) |
| `dry_run` | boolean | No | `false` | Show what would be created without actually creating issues |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the sync_discovered_work skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("sync_discovered_work", '{
  "auto_create": false,
  "priority_filter": "example-priority_filter",
  "type_filter": "example-type_filter",
  "parent_epic": "example-parent_epic",
  "dry_run": false
}')
```

### Via Command (if configured)

```
/sync-discovered-work
```

## MCP Tools Used

- `jira_create_issue`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/sync_discovered_work.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/sync_discovered_work.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
