---
description: Begin working on a Jira issue
agent: developer
---

Start working on Jira issue $1. This will:
- Fetch issue details from Jira
- Create a feature branch
- Set up your development context
- Update work tracking in memory

Execute: skill_run("start_work", '{"issue_key": "$1"}')

**Usage:** `/start-work AAP-12345`
