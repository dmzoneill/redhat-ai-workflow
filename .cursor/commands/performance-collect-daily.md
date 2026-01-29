# Collect Daily

Collect daily performance data and map to PSE competencies.

## Instructions

```text
skill_run("performance/collect_daily", '{"date": ""}')
```

## What It Does

Collect daily performance data and map to PSE competencies.

Fetches:
- Jira: Issues resolved/created today
- GitLab: MRs merged, reviews given
- GitHub: PRs merged (upstream contributions)
- Git: Commits across configured repos

Then maps each item to competencies using keyword rules and AI fallback,
calculates points, and saves to the daily JSON file.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `date` | Date to collect data for (YYYY-MM-DD). Defaults to today. | No |
