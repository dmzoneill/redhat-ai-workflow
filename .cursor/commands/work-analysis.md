# 📊 Work Analysis Report

Analyze your work activity across repositories for management reporting and time tracking.

## Usage

**Default (past 6 months):**
```text
skill_run("work_analysis", '{}')
```

**Custom date range:**
```text
skill_run("work_analysis", '{"start_date": "2025-01-01", "end_date": "2025-01-19"}')
```

**Just start date (end defaults to today):**
```text
skill_run("work_analysis", '{"start_date": "2024-10-01"}')
```

## What It Analyzes

| Source | Data |
|--------|------|
| **Git** | Commits from all configured repos (categorized by type) |
| **Jira** | Issues completed, story points |
| **GitLab** | MRs created, reviewed, merged |

## Work Categories

Commits are automatically categorized into:

- **DevOps** - CI/CD, deployments, infrastructure, k8s, containers
- **Development** - Features, enhancements, refactoring
- **Testing** - Tests, coverage, fixtures
- **Bug Fixes** - Fixes, hotfixes, patches
- **Documentation** - Docs, READMEs, comments
- **Incident Response** - Alerts, outages, rollbacks
- **Chores/Maintenance** - Cleanup, linting, dependency updates

## Report Sections

The generated report includes:

1. **Summary** - Total commits, lines changed, MRs, Jira issues
2. **Work Distribution** - Breakdown by category with percentages
3. **By Repository** - Activity per repo with primary category
4. **Jira Issues Completed** - List of closed issues
5. **MRs Created/Reviewed** - Recent merge request activity
6. **Recent Commits** - Sample of commits with categories

## Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `start_date` | string | 6 months ago | Start date (YYYY-MM-DD) |
| `end_date` | string | today | End date (YYYY-MM-DD) |
| `author` | string | config user | Filter by single author email |
| `authors` | list | [] | List of author emails (for multiple accounts) |
| `repos` | list | all repos | Specific repos to analyze |
| `exclude_repos` | list | ["redhat-ai-workflow"] | Repos to exclude |

## Examples

```text
# Sprint review (last 2 weeks)
skill_run("work_analysis", '{"start_date": "2025-01-06", "end_date": "2025-01-19"}')

# Quarterly report
skill_run("work_analysis", '{"start_date": "2024-10-01", "end_date": "2024-12-31"}')

# Specific repo only
skill_run("work_analysis", '{"repos": ["automation-analytics-backend"]}')

# Multiple author accounts (for commits made with different emails)
skill_run("work_analysis", '{"authors": ["daoneill@redhat.com", "dmz.oneill@gmail.com"]}')
```

## Use Cases

- **Sprint reviews** - Show work completed during sprint
- **Management reports** - Effort distribution for time tracking
- **Performance reviews** - 6-month activity summary
- **Team planning** - Understand where time is being spent
