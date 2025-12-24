# Review MR (Static Analysis)

Quick code review of a Merge Request - checks format, description, pipelines, and code patterns.

## Instructions

Run a static analysis review (no local tests):

```
skill_run("review_pr", '{"mr_id": $MR_ID}')
```

This will:
1. Fetch MR details from GitLab
2. Extract and validate Jira key from title
3. Check commit format (AAP-XXXXX - type(scope): description)
4. Verify MR description is adequate
5. Check GitLab and Konflux pipeline status
6. Analyze code for security, memory leaks, race conditions
7. Auto-approve or post feedback based on findings

## Examples

```bash
# By MR ID
skill_run("review_pr", '{"mr_id": 1450}')

# By Jira key (finds associated MR)
skill_run("review_pr", '{"issue_key": "AAP-60420"}')

# By GitLab URL
skill_run("review_pr", '{"url": "https://gitlab.cee.redhat.com/automation-analytics/automation-analytics-backend/-/merge_requests/1450"}')
```

