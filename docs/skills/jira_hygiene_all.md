# 🧹 jira_hygiene_all

> Batch hygiene checks on all your assigned Jira issues

## Overview

The `jira_hygiene_all` skill runs hygiene checks on all Jira issues assigned to you. It fetches your issue backlog and runs the `jira_hygiene` skill on each one, providing a consolidated report of issue health. This is useful for scheduled nightly cleanup of your issue backlog.

## Quick Start

```text
skill_run("jira_hygiene_all", '{}')
```

Or with filters:

```text
skill_run("jira_hygiene_all", '{"status": "In Progress", "auto_fix": true}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `status` | string | No | `""` | Filter by status (e.g., "In Progress", "New"). Empty = all statuses |
| `limit` | integer | No | `200` | Maximum number of issues to process |
| `auto_fix` | boolean | No | `true` | Automatically fix issues where possible |
| `auto_transition` | boolean | No | `true` | Auto-transition New to Refinement when ready |
| `dry_run` | boolean | No | `false` | Show what would be fixed without making changes |

## What It Does

1. **Load Developer Persona** - Ensures Jira tools are available
2. **Fetch My Issues** - Retrieves all issues assigned to you using `jira_my_issues`
3. **Parse Issues** - Extracts issue keys (AAP-XXXXX pattern)
4. **Run Batch Hygiene** - For each issue:
   - Invokes `jira_hygiene` skill
   - Captures result (healthy, fixed, needs_attention, error)
   - Tracks health scores
5. **Build Summary** - Generates consolidated report with:
   - Overall statistics
   - Issues needing manual attention
   - Detailed per-issue results
6. **Log Session** - Records batch hygiene to memory

## Health Categories

| Status | Description | Emoji |
|--------|-------------|-------|
| Healthy | All checks passed (100%) | ✅ |
| Fixed | Issues were automatically fixed | 🔧 |
| Needs Attention | Manual intervention required | ⚠️ |
| Error | Failed to process | ❌ |

## Example Usage

### Process All Issues

```python
skill_run("jira_hygiene_all", '{}')
```

### Filter by Status

```python
skill_run("jira_hygiene_all", '{"status": "In Progress"}')
```

### Dry Run Preview

```python
skill_run("jira_hygiene_all", '{"dry_run": true}')
```

### Disable Auto-Fix

```python
skill_run("jira_hygiene_all", '{"auto_fix": false}')
```

### Limit Processing

```python
skill_run("jira_hygiene_all", '{"limit": 10}')
```

## Example Output

```text
## 🧹 Batch Jira Hygiene Report

**Issues Found:** 15
**Processed:** 15

### Summary
- ✅ **Healthy:** 8
- 🔧 **Fixed:** 4
- ⚠️ **Needs Attention:** 3

### ⚠️ Issues Needing Manual Attention
- [AAP-12345](https://issues.redhat.com/browse/AAP-12345)
- [AAP-12348](https://issues.redhat.com/browse/AAP-12348)
- [AAP-12350](https://issues.redhat.com/browse/AAP-12350)

### Details
- ✅ AAP-12340 (100%)
- ✅ AAP-12341 (100%)
- 🔧 AAP-12342 (fixed)
- ⚠️ AAP-12345 (65%)
- ✅ AAP-12346 (100%)
- 🔧 AAP-12347 (fixed)
- ⚠️ AAP-12348 (50%)
- ✅ AAP-12349 (100%)
- ⚠️ AAP-12350 (70%)
- ... and 6 more

---

### Quick Actions

**Fix specific issue:**
```
skill_run("jira_hygiene", '{"issue_key": "AAP-12345"}')
```

**Run again:**
```
skill_run("jira_hygiene_all", '{}')
```
```

## Outputs

| Output | Description |
|--------|-------------|
| `summary` | Full markdown report |
| `stats.total_found` | Total issues found |
| `stats.processed` | Number processed |
| `stats.healthy` | Number passing all checks |
| `stats.fixed` | Number automatically fixed |
| `stats.needs_attention` | Number needing manual work |

## What Gets Checked

Each issue is evaluated by `jira_hygiene` for:

- **Title format** - Follows naming conventions
- **Description quality** - Has meaningful content
- **Acceptance criteria** - Includes clear criteria
- **Labels** - Has appropriate labels
- **Story points** - Estimated for planning
- **Component** - Assigned to correct component
- **Sprint** - Assigned to active sprint

## MCP Tools Used

- `persona_load` - Load developer persona
- `jira_my_issues` - Fetch assigned issues
- `skill_run` - Invoke `jira_hygiene` on each issue
- `memory_session_log` - Log batch run

## Scheduling

This skill is ideal for nightly runs:

```text
# Run at 11 PM on weekdays
0 23 * * 1-5 skill_run("jira_hygiene_all", '{"auto_fix": true}')
```

## Related Skills

- [jira_hygiene](./jira_hygiene.md) - Check single issue hygiene
- [pr_jira_audit](./pr_jira_audit.md) - Audit PRs for Jira references
- [sync_discovered_work](./sync_discovered_work.md) - Sync discovered work to Jira
