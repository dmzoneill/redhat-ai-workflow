# 📊 work_analysis

> Analyze work activity across repositories for management reporting and time tracking

## Overview

The `work_analysis` skill provides comprehensive work activity analysis across all configured repositories. It gathers commits, categorizes work by type (DevOps, Development, Testing, Bug Fixes, etc.), pulls Jira and GitLab MR data, and generates a detailed markdown report showing effort distribution over a configurable time period.

This skill is ideal for sprint reviews, management reports, performance evaluations, and time tracking.

## Quick Start

```text
skill_run("work_analysis", '{}')
```

Or use the Cursor command:

```text
/work-analysis
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `start_date` | string | No | 6 months ago | Start date in YYYY-MM-DD format |
| `end_date` | string | No | today | End date in YYYY-MM-DD format |
| `author` | string | No | config email | Filter by author email |
| `authors` | list | No | `[]` | List of author emails (for multiple accounts) |
| `repos` | list | No | `[]` | Specific repos to analyze |
| `exclude_repos` | list | No | `["redhat-ai-workflow"]` | Repos to exclude from analysis |

## What It Does

1. **Loads Configuration** - Determines which repositories to analyze and date range
2. **Collects Git Commits** - Runs `git log` on each repo to gather commit history
3. **Categorizes Work** - Classifies each commit into work categories using pattern matching:
   - **DevOps** - CI/CD, deployments, infrastructure, Kubernetes, Docker
   - **Development** - Features, enhancements, refactoring
   - **Testing** - Tests, coverage, fixtures, mocking
   - **Bug Fixes** - Fixes, patches, hotfixes
   - **Documentation** - READMEs, docstrings, comments
   - **Incident Response** - Alerts, outages, rollbacks
   - **Chores/Maintenance** - Cleanup, linting, dependency updates
4. **Fetches Jira Data** - Gets completed issues and story points
5. **Fetches GitLab Data** - Gets MRs created, reviewed, and merged
6. **Generates Report** - Creates markdown with tables and statistics
7. **Saves to Memory** - Records analysis for future reference

## Example Usage

### Default Analysis (Last 6 Months)

```python
skill_run("work_analysis", '{}')
```

### Custom Date Range

```python
skill_run("work_analysis", '{"start_date": "2025-01-01", "end_date": "2025-03-31"}')
```

### Specific Repositories

```python
skill_run("work_analysis", '{"repos": ["automation-analytics-backend", "automation-hub"]}')
```

### Multiple Author Emails

```python
skill_run("work_analysis", '{"authors": ["jsmith@redhat.com", "john.smith@company.com"]}')
```

## Example Output

```text
# Work Analysis Report

**Period:** 2025-07-01 to 2026-01-26
**Author:** Dave O'Neill
**Repositories Analyzed:** 4

---

## Summary

- **Total Commits:** 234
- **Lines Changed:** +15,432 / -8,721
- **MRs Created:** 28
- **MRs Reviewed:** 45
- **MRs Merged:** 24
- **Jira Issues Completed:** 18

## Work Distribution

| Category | Commits | Lines (+/-) | % of Work |
|----------|---------|-------------|-----------|
| Development | 98 | +8,234/-3,421 | 42% |
| DevOps | 56 | +3,210/-2,100 | 24% |
| Bug Fixes | 42 | +1,890/-1,456 | 18% |
| Testing | 28 | +1,567/-890 | 12% |
| Documentation | 10 | +531/-854 | 4% |

## By Repository

| Repository | Commits | Lines (+/-) | Primary Category |
|------------|---------|-------------|------------------|
| automation-analytics-backend | 156 | +10,234/-5,421 | Development |
| app-interface | 45 | +3,210/-2,100 | DevOps |
| automation-hub | 33 | +1,988/-1,200 | Bug Fixes |
```

## MCP Tools Used

- `git_log` (via subprocess) - Commit history with numstat
- `jira_search` - Completed issues and worked issues
- `gitlab_mr_list` - MRs created and reviewed
- `memory_session_log` - Session logging
- `memory_write` - Save analysis to patterns

## Related Skills

- [standup_summary](./standup_summary.md) - Generate daily standup notes
- [weekly_summary](./weekly_summary.md) - Weekly work summary
- [discovered_work_summary](./discovered_work_summary.md) - Summary of discovered work items
