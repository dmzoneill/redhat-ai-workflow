---
name: work-analysis
description: Analyze work activity across all configured repositories for a given time period
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: work_analysis.yaml
  executable: "true"
---

# work_analysis

Analyze work activity across all configured repositories for a given time period.

This skill:
- Gathers commits from all repos (excluding redhat-ai-workflow by default)
- Categorizes work into: DevOps, Development, Testing, Bug Fixes, Documentation,
  Code Review, Incident Response, and Other
- Pulls Jira data (issues completed, story points)
- Pulls GitLab MR data (created, reviewed, merged)
- Generates a markdown report showing effort distribution

Useful for sprint reviews, management reports, and time tracking.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("work_analysis", '{
  "start_date": "example-start_date",
  "end_date": "example-end_date",
  "author": "example-author",
  "authors": [],
  "repos": [],
  "exclude_repos": ['redhat-ai-workflow']
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab and Jira tools**
2. **Load configuration and determine repos to analyze**
3. **Define work category patterns for commit classification**
4. **Collect commits from all repos using subprocess**
5. **Categorize commits by work type**
6. **Get Jira issues completed in date range**
7. **Get Jira issues worked on in date range**
8. **Parse Jira search results**
9. **Get MRs created in date range**
10. **Get MRs reviewed in date range**
11. **Parse GitLab MR data**
12. **Generate markdown report**
13. **Log work analysis to session**
14. **Save analysis summary to memory for future reference**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `start_date` | string | No | `-` | Start date in YYYY-MM-DD format (default: 6 months ago) |
| `end_date` | string | No | `-` | End date in YYYY-MM-DD format (default: today) |
| `author` | string | No | `-` | Filter by author email (default: current user from config) |
| `authors` | list | No | `[]` | List of author emails to include (for multiple accounts). Overrides 'author' if provided. |
| `repos` | list | No | `[]` | Specific repos to analyze (default: all from config except excluded) |
| `exclude_repos` | list | No | `['redhat-ai-workflow']` | Repos to exclude from analysis |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the work_analysis skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("work_analysis", '{
  "start_date": "example-start_date",
  "end_date": "example-end_date",
  "author": "example-author",
  "authors": [],
  "repos": [],
  "exclude_repos": ['redhat-ai-workflow']
}')
```

### Via Command (if configured)

```
/work-analysis
```

## MCP Tools Used

- `gitlab_mr_list`
- `jira_search`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/work_analysis.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/work_analysis.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
