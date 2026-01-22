# Review PR (Multi-Agent)

Comprehensive PR review using multiple specialized agents.

## Instructions

```text
skill_run("review_pr_multiagent", '{"mr_id": $MR_ID}')
```

## What It Does

Uses multiple specialized agents to review different aspects:
1. **Code Quality Agent** - Style, patterns, best practices
2. **Security Agent** - Vulnerability scanning
3. **Performance Agent** - Performance implications
4. **Test Agent** - Test coverage analysis

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `mr_id` | Merge request ID | Yes |
| `project` | GitLab project | No (auto-detected) |

## Examples

```bash
# Full multi-agent review
skill_run("review_pr_multiagent", '{"mr_id": 1450}')
```

## See Also

- `/review-pr` - Quick static analysis review
- `/review-mr-with-tests` - Review with local test execution
