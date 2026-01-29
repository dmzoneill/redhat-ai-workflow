# Performance Persona

PSE competency tracking, quarterly reviews, and performance reporting.

## Overview

The performance persona is designed for tracking work accomplishments and mapping them to PSE (Principal Software Engineer) competency frameworks for quarterly reviews.

## Tool Modules

| Module | Tools | Purpose |
|--------|-------|---------|
| workflow | 51 | Core system tools |
| performance | 13 | PSE competency tracking |
| jira_basic | 17 | Fetch resolved issues |
| gitlab_basic | 18 | Fetch merged MRs |
| git_basic | 28 | Fetch commits |

**Total:** ~127 tools

## Key Skills

| Skill | Description |
|-------|-------------|
| performance/collect_daily | Collect daily performance data |
| performance/backfill_missing | Backfill missing weekdays |
| performance/evaluate_questions | AI evaluation of quarterly questions |
| performance/export_report | Export quarterly report |

## Use Cases

- Daily performance data collection
- Quarterly self-assessment prep
- Evidence gathering for promotions
- Work activity analysis

## Loading

```
persona_load("performance")
```

## Data Sources

The performance persona collects data from:

1. **Git commits** - Code contributions
2. **Jira issues** - Resolved issues
3. **GitLab MRs** - Merged merge requests
4. **Session logs** - Daily work activity

## See Also

- [Personas Overview](./README.md)
- [Performance Tools](../tool-modules/performance.md)
