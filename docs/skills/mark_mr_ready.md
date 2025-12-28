# ✅ mark_mr_ready

> Mark a draft MR as ready for review and notify the team

## Overview

The `mark_mr_ready` skill removes draft status from a merge request and posts a notification to the team Slack channel asking for review.

## When to Use

- You have a draft MR that's ready for review
- You want to notify the team when marking an MR ready
- Converting WIP merge requests to ready status

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mr_id` | string | ✅ | - | MR ID (e.g., "1459" or "!1459") |
| `project` | string | ❌ | automation-analytics-backend | GitLab project path |
| `issue_key` | string | ❌ | - | Jira issue key to update |
| `update_jira` | boolean | ❌ | true | Update Jira status to "In Review" |

## What It Does

```mermaid
graph LR
    A[Get MR Details] --> B[Remove Draft Status]
    B --> C[Post to Slack]
    C --> D[Update Jira]

    style B fill:#10b981,stroke:#059669,color:#fff
    style C fill:#6366f1,stroke:#4f46e5,color:#fff
```

1. **Get MR Details** - Fetches current MR info (title, branch, Jira key)
2. **Remove Draft** - Uses `gitlab_mr_update` with `draft: false`
3. **Slack Notification** - Posts to team channel with Jira and MR links
4. **Update Jira** - Moves issue to "In Review" status

## Usage Examples

**Mark MR ready:**
```
Mark MR !1459 as ready for review
```

**With specific project:**
```
Mark MR 1459 in insights/frontend as ready
```

**With Jira update:**
```
Make !1459 ready and update AAP-12345 to In Review
```

## Slack Notification

When the MR is marked ready, a message is posted to the team channel:

```
🔀 *MR Ready for Review*

📋 *Jira:* AAP-12345
🔗 *MR:* !1459 Fix billing calculation bug
📁 *Repo:* automation-analytics-backend

Please review when you have a moment 🙏
```

## Output

```markdown
## ✅ MR !1459 Marked Ready

| Step | Result |
|------|--------|
| Remove draft | ✅ Done |
| Slack notification | ✅ Posted |
| Jira status | ✅ Updated |

**MR:** https://gitlab.cee.redhat.com/.../merge_requests/1459
**Jira:** https://issues.redhat.com/browse/AAP-12345
```

## Related Skills

- [create_mr](./create_mr.md) - Create a new MR (can be non-draft)
- [review_pr](./review_pr.md) - Review an MR
- [rebase_pr](./rebase_pr.md) - Rebase before marking ready

## Tools Used

- `gitlab_mr_view` - Get MR details
- `gitlab_mr_update` - Remove draft status
- `slack_post_team` - Post to team channel
- `jira_set_status` - Update Jira status
