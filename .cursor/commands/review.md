# /review

**Description:** Review a specific GitLab Merge Request with detailed analysis.

**Usage:**
```text
skill_run("review_pr", '{"mr_id": 1450}')
```

**Options:**
- `mr_id`: The GitLab MR number (required)
- `project`: GitLab project path (default: automation-analytics-backend)
- `run_tests`: Run local tests (default: false)
  ```text
  skill_run("review_pr", '{"mr_id": 1450, "run_tests": true}')
```

**What it does:**

1. **Fetches MR details** - Title, description, author, status
2. **Analyzes changes** - Files modified, additions/deletions
3. **Checks pipeline status** - CI/CD results
4. **Reviews code quality** - Looks for common issues
5. **Optionally runs tests** - Local pytest execution
6. **Suggests action** - Approve, request changes, or needs discussion

**Example:**
```text
/review 1450
```

This runs:
```text
skill_run("review_pr", '{"mr_id": 1450}')
```

**With local tests:**
```text
skill_run("review_pr", '{"mr_id": 1450, "run_tests": true}')
```

**From URL:**
```text
skill_run("review_pr", '{"url": "https://gitlab.cee.redhat.com/automation-analytics/automation-analytics-backend/-/merge_requests/1450"}')
```

**Quick review all open PRs:**
```text
skill_run("review_all_prs")
```
