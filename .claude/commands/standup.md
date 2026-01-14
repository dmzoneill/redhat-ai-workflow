---
name: standup
description: "**Description:** Generate your daily standup summary from recent activity."
arguments:
  - name: days
---
# /standup

**Description:** Generate your daily standup summary from recent activity.

**Usage:**
```text
skill_run("standup_summary")
```

**Options:**
- `days`: How many days back to look (default: 1)
  ```text
  skill_run("standup_summary", '{"days": 2}')
```
- `repo`: Specific repository path
  ```text
  skill_run("standup_summary", '{"repo_name": "automation-analytics-backend"}')
```
- `issue_key`: Focus on a specific Jira issue
  ```text
  skill_run("standup_summary", '{"issue_key": "AAP-12345"}')
```

**What it generates:**

### ✅ What I Did
- Recent commits with links to Jira issues
- Issues closed (moved to Done)
- PRs reviewed

### 🔄 What I'm Working On
- Issues in "In Progress" or "In Review" status
- Open MRs

### 🚧 Blockers
- (Manual input - skill prompts if needed)

**Example Output:**
```text
## 📋 Standup Summary
**Date:** 2025-12-24
**Author:** Dave O'Neill

### ✅ What I Did
**Commits:** 5
- `a1b2c3d` AAP-12345 - feat: Add billing integration
- `e4f5g6h` AAP-12346 - fix: Handle null response
...

### 🔄 What I'm Working On
- [AAP-12345] Billing integration feature
- [AAP-12347] Performance optimization

### 🚧 Blockers
- None
```

**Quick aliases:**
- `/standup` - Yesterday's summary (default)
- `/standup 3` - Last 3 days (for Monday standups)
