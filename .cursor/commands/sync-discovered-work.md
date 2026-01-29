# Sync Discovered Work

Review and sync discovered work items to Jira.

## Instructions

```text
skill_run("sync_discovered_work", '{"auto_create": "", "priority_filter": "", "type_filter": "", "parent_epic": "", "dry_run": ""}')
```

## What It Does

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

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `auto_create` | Automatically create Jira issues for all pending items (default: false, review first) | No |
| `priority_filter` | Only sync items with this priority or higher (low, medium, high, critical) | No |
| `type_filter` | Only sync items of this type (tech_debt, bug, improvement, etc.) | No |
| `parent_epic` | Epic key to link all created issues to (e.g., AAP-50000) | No |
| `dry_run` | Show what would be created without actually creating issues | No |
