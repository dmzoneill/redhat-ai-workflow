---
description: Create merge request with validation
agent: developer
---

Create a merge request for Jira issue $1. This will:
- Validate your branch and commits
- Push to GitLab
- Create an MR with proper formatting
- Link to the Jira issue

Execute: skill_run("create_mr", '{"issue_key": "$1"}')

**Usage:** `/create-mr AAP-12345`
