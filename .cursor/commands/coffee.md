# ☕ Morning Coffee Briefing

Your daily standup assistant - everything you need at the start of your work day.

## Instructions

Get your morning briefing:

```
skill_run("coffee")
```

## What You'll Get

| Section | Description |
|---------|-------------|
| 📅 Calendar | Today's meetings with Meet links |
| 📧 Email | Unread count, categorized (people vs newsletters) |
| 🔀 PRs | Your open PRs, feedback waiting, failed pipelines |
| 👀 Reviews | PRs assigned to you for review |
| 🧪 Ephemeral | Your active test environments with expiry times |
| 📝 Yesterday | Your commits from yesterday (for standup) |
| 📋 Jira | Sprint activity for the day/week |
| 🚀 Merges | Recently merged code in aa-backend |
| 🚨 Alerts | Any firing Prometheus alerts |
| 🎯 Actions | Smart suggestions based on all the above |

## Options

```bash
# Look back further in history
skill_run("coffee", '{"days_back": 7}')

# Full email processing (mark read & archive)
skill_run("coffee", '{"full_email_scan": true, "auto_archive_email": true}')
```

## First Time Setup

If email isn't working, you need to enable Gmail API:

```
/setup-gmail
```

This adds Gmail scopes to your existing Google OAuth.

## Quick Summary

Just want the highlights without the full briefing?

```
skill_run("coffee", '{"days_back": 1}')
```

