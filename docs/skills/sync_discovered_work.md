# 🔄 sync_discovered_work

> Review and sync discovered work items to Jira

## Overview

The `sync_discovered_work` skill reviews pending discovered work items and creates Jira issues for them. During skill execution (like `review_pr`, `start_work`, or `investigate_alert`), work items are discovered that need follow-up but aren't part of the current task. This skill helps you manage that backlog by reviewing, filtering, and optionally creating Jira issues.

## Quick Start

Review pending items (no changes):

```text
skill_run("sync_discovered_work", '{}')
```

Create Jira issues automatically:

```text
skill_run("sync_discovered_work", '{"auto_create": true}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `auto_create` | boolean | No | `false` | Automatically create Jira issues for pending items |
| `priority_filter` | string | No | - | Only sync items with this priority or higher (`low`, `medium`, `high`, `critical`) |
| `type_filter` | string | No | - | Only sync items of this type |
| `parent_epic` | string | No | - | Epic key to link all created issues to (e.g., `AAP-50000`) |
| `dry_run` | boolean | No | `false` | Show what would be created without actually creating |

## What It Does

1. **Loads Discovered Work** - Retrieves all discovered work items from memory
2. **Filters Items** - Applies priority and type filters if specified
3. **Groups Items** - Organizes by type and priority for review
4. **Builds Review Summary** - Shows statistics and categorization
5. **Lists Pending Items** - Displays detailed list of items needing attention
6. **Creates Jira Issues** (if `auto_create: true`):
   - Creates appropriately typed issues (Task, Bug, Story)
   - Adds labels based on work type
   - Links to parent epic if specified
   - Marks items as synced in memory
7. **Reports Results** - Shows created issues and any failures

## Work Types and Jira Mapping

| Work Type | Jira Issue Type | Labels |
|-----------|-----------------|--------|
| `tech_debt` | Task | `tech-debt`, `discovered-work` |
| `bug` | Bug | `discovered-work` |
| `improvement` | Story | `improvement`, `discovered-work` |
| `missing_test` | Task | `testing`, `discovered-work` |
| `missing_docs` | Task | `documentation`, `discovered-work` |
| `security` | Bug | `security`, `discovered-work` |
| `discovered_work` | Task | `discovered-work` |

## Example Usage

### Review Only (Default)

```python
skill_run("sync_discovered_work", '{}')
```

### Dry Run

```python
skill_run("sync_discovered_work", '{"dry_run": true}')
```

### Create All Pending Issues

```python
skill_run("sync_discovered_work", '{"auto_create": true}')
```

### Create High Priority Only

```python
skill_run("sync_discovered_work", '{"auto_create": true, "priority_filter": "high"}')
```

### Create Tech Debt Only

```python
skill_run("sync_discovered_work", '{"auto_create": true, "type_filter": "tech_debt"}')
```

### Link to Epic

```python
skill_run("sync_discovered_work", '{"auto_create": true, "parent_epic": "AAP-50000"}')
```

## Example Output

### Review Mode

```text
## 📋 Discovered Work Summary

**Total items:** 8
**Pending sync:** 5
**Already synced:** 3

### By Type
- 🔧 **tech_debt**: 3
- 🐛 **bug**: 2
- ✨ **improvement**: 2
- 🧪 **missing_test**: 1

### By Priority
- 🟠 **high**: 2
- 🟡 **medium**: 4
- 🟢 **low**: 2

### By Source Skill
- `review_pr`: 4
- `start_work`: 3
- `investigate_alert`: 1

## 📝 Pending Items

### 1. 🔧 Add connection pooling to database client
**Type:** tech_debt | **Priority:** 🟠 high
**Source:** `review_pr`
**Related MR:** !1459
**File:** `app/db/client.py:45`
**Discovered:** 2026-01-24

### 2. 🐛 Race condition in cache invalidation
**Type:** bug | **Priority:** 🟠 high
**Source:** `investigate_alert`
**Notes:** Seen during high load, needs mutex

---

## 🎯 Next Steps

To create Jira issues for these items:

**Create all:**
```
skill_run("sync_discovered_work", '{"auto_create": true}')
```

**Create high priority only:**
```
skill_run("sync_discovered_work", '{"auto_create": true, "priority_filter": "high"}')
```
```

### After Creation

```text
---

## ✅ Created Issues

- Synced: AAP-61234
- Synced: AAP-61235
- Synced: AAP-61236

**Summary:** 3 created, 0 failed
```

## MCP Tools Used

- `persona_load` - Load developer persona for Jira tools
- `jira_create_issue` - Create Jira issues
- `memory_session_log` - Log sync action

## Related Skills

- [discovered_work_summary](./discovered_work_summary.md) - View summary of discovered work
- [jira_hygiene](./jira_hygiene.md) - Clean up Jira issue quality
- [create_jira_issue](./create_jira_issue.md) - Create individual Jira issues
