---
description: Collect today's performance data and map to PSE competencies
---

Run the daily performance collection to capture today's work activities.

This will:
1. Fetch resolved Jira issues
2. Fetch merged GitLab MRs and reviews given
3. Fetch merged GitHub PRs (upstream contributions)
4. Scan local git repos for commits
5. Map each item to PSE competencies
6. Calculate points and save to daily file
7. Update the quarter summary

@skill performance/collect_daily.yaml
