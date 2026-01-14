# 💬 Slack Persona

> Autonomous Slack responder and team assistant

## Overview

The Slack persona is designed for autonomous Slack integration. It monitors channels, detects intent, and responds to requests using available skills and tools.

## Quick Load

```text
Load the slack agent
```

## Tools Loaded

| Module | Tools | Description |
|--------|-------|-------------|
| [slack](../tool-modules/slack.md) | 13 | Slack messaging |
| [jira](../tool-modules/jira.md) | 24 | Issue tracking |
| [gitlab](../tool-modules/gitlab.md) | 35 | MRs and pipelines |

**Total:** ~85 tools (4 modules)

## Installation

### 1. Prerequisites

```bash
# Python 3.10+
python3 --version

# Install dependencies
cd ~/src/redhat-ai-workflow
pip install -e .

# D-Bus support (for daemon control)
pip install dbus-next
```

### 2. Get Slack Credentials

The bot uses Slack's web API (not official Bot API). Extract credentials from your browser:

```bash
# Automatic extraction (requires Chrome)
pip install pycookiecheat
python scripts/get_slack_creds.py
```

Or manually from Chrome DevTools:
1. Open Slack in Chrome
2. DevTools → Application → Cookies → `d` cookie
3. DevTools → Application → Local Storage → `xoxc` token

### 3. Configure

Add credentials to `config.json`:

```json
{
  "slack": {
    "auth": {
      "xoxc_token": "xoxc-...",
      "d_cookie": "xoxd-...",
      "workspace_id": "E...",
      "host": "your-company.enterprise.slack.com"
    },
    "channels": {
      "team": {
        "id": "C089F16L30T",
        "name": "aa-api-team-test",
        "description": "Team channel for notifications"
      },
      "standup": {
        "id": "C089F16L30T",
        "name": "aa-api-team-test",
        "description": "Daily standup summaries"
      }
    },
    "alert_channels": {
      "C089XXXXXX": {
        "name": "aleets",
        "environment": "stage"
      }
    },
    "user_mapping": {
      "gitlab_username": "U_SLACK_USER_ID"
    }
  }
}
```

### 4. Configure Claude AI (Optional)

For autonomous AI-powered responses, set up Vertex AI:

```bash
# In your shell profile (~/.bashrc or ~/.zshrc)
export CLAUDE_CODE_USE_VERTEX=1
export ANTHROPIC_VERTEX_PROJECT_ID="your-gcp-project"

# OR for direct Anthropic API:
export ANTHROPIC_API_KEY="your-api-key"
```

## Running the Daemon

### Quick Start

```bash
# Test credentials first
make slack-test

# Run in foreground (Ctrl+C to stop)
make slack-daemon

# Run with Claude AI integration
make slack-daemon-llm

# Run in background with D-Bus IPC
make slack-daemon-bg
```

### Makefile Targets

| Target | Description |
|--------|-------------|
| `make slack-daemon` | Foreground, Ctrl+C to stop |
| `make slack-daemon-bg` | Background with D-Bus IPC |
| `make slack-daemon-stop` | Stop background daemon |
| `make slack-daemon-logs` | Tail the log file |
| `make slack-daemon-status` | Check if running |
| `make slack-daemon-verbose` | Foreground with debug logging |
| `make slack-daemon-dry` | Dry-run mode (no messages sent) |
| `make slack-test` | Validate credentials |

### D-Bus Control Commands

Once running with D-Bus enabled:

```bash
# Check status
make slack-status

# View pending messages awaiting approval
make slack-pending

# Approve a message
make slack-approve ID=msg_12345

# Approve all pending
make slack-approve-all

# Reject a message
make slack-reject ID=msg_12345

# Send a message
make slack-send TARGET=C12345678 MSG="Hello team!"
make slack-send TARGET=@username MSG="Hello!"

# Watch for new messages (live)
make slack-watch

# Reload configuration
make slack-reload
```text

### Log Location

- **Log file:** `/tmp/slack-daemon.log`
- **PID file:** `/tmp/slack-daemon.pid`
- **SQLite DB:** `slack_state.db` (in project root)

## Skills Available

| Skill | Description |
|-------|-------------|
| [⚡ start_work](../skills/start_work.md) | Start working on issue |
| [🚀 create_mr](../skills/create_mr.md) | Create merge request |
| [👀 review_pr](../skills/review_pr.md) | Review a PR |
| [📝 check_my_prs](../skills/check_my_prs.md) | Check your PRs |
| [✅ close_issue](../skills/close_issue.md) | Close an issue |
| [📊 standup_summary](../skills/standup_summary.md) | Generate standup |
| [📋 jira_hygiene](../skills/jira_hygiene.md) | Check issue quality |
| [🔁 sync_branch](../skills/sync_branch.md) | Sync branch |
| [🔄 rebase_pr](../skills/rebase_pr.md) | Rebase a PR |
| [🚨 investigate_slack_alert](../skills/investigate_slack_alert.md) | Investigate Prometheus alerts |

## Communication Style

The Slack agent uses concise, Slack-appropriate formatting:

**Good Response:**
```
📋 *AAP-12345*: Add REST endpoint for user preferences
Status: In Progress | Assignee: @david
[View in Jira](link)
```text

**Not Like This:**
```
I found the Jira issue you requested. Here are the details...
The issue titled "Add REST endpoint for user preferences"...
(too verbose for Slack)
```text

## Intent Detection

| Trigger | Intent | Action |
|---------|--------|--------|
| "AAP-12345" | jira_query | Show issue details |
| "!123", "MR 123" | pr_status | Show MR status |
| "my PRs", "my MRs" | check_my_prs | Run skill |
| "prod down", "alert" | prod_debug | Offer debug_prod |
| "start AAP-12345" | start_work | Offer start_work |
| "standup", "status" | standup | Run standup_summary |

## Alert Handling

The bot automatically detects Prometheus alerts in configured alert channels:

1. **Detects alert format** - Looks for `[FIRING]`, `AlertManager`, severity labels
2. **Acknowledges** - Adds 👀 reaction to show it's investigating
3. **Runs investigation** - Uses `investigate_slack_alert` skill
4. **Reports findings** - Posts summary with pod status, events, recommendations
5. **Offers actions** - Can create Jira issues, silence alerts, escalate

## Example Interactions

### Jira Query

```
User: What's the status of AAP-12345?

Bot: 📋 *AAP-12345*: Implement caching layer
     Status: In Progress 🔄
     Assignee: @jsmith
     [View in Jira](https://issues.redhat.com/browse/AAP-12345)
```text

### MR Status

```
User: Check MR 456

Bot: 🦊 *!456*: AAP-12345 - feat: Add caching
     Author: jsmith | Target: main
     Pipeline: Passed ✅
     [View MR](https://gitlab.../456)
```text

### Alert Investigation

```
AlertManager: [FIRING:1] HighErrorRate - tower-analytics-api

Bot: 👀 Investigating alert...

     🚨 *HighErrorRate* - tower-analytics-api
     Environment: stage

     📊 **Pod Status:**
     - tower-analytics-api-abc123: Running (3 restarts)

     📋 **Recent Events:**
     - OOMKilled 2h ago

     💡 **Recommendation:**
     Memory limit may be too low. Consider increasing limits.

     🎯 Actions:
     • Create Jira issue
     • Silence alert (1h)
     • View full logs
```text

### Help

```
User: @bot help

Bot: 👋 Here's what I can help with:

     📋 *Jira* - "AAP-12345" or "what's AAP-12345"
     🦊 *MRs* - "MR 123" or "check my PRs"
     🚀 *Actions* - "start AAP-12345" or "create MR"
     📊 *Status* - "standup" or "my work"
```

## User Classification

The agent adjusts its response style based on who's asking:

| Category | Style | Auto-respond? |
|----------|-------|---------------|
| **Teammates** | Casual, emojis ✅ | Yes |
| **Managers** | Formal, no emojis | Review first |
| **Unknown** | Professional | Yes |

## Troubleshooting

### Credentials Expired

Slack web tokens expire periodically. Re-extract:

```bash
python scripts/get_slack_creds.py
# Update config.json with new values
make slack-reload  # If daemon is running
```

### Daemon Won't Start

```bash
# Check for existing process
make slack-daemon-status

# Force stop and clean
make slack-daemon-stop
rm -f /tmp/slack-daemon.pid /tmp/slack-daemon.lock

# Check logs
cat /tmp/slack-daemon.log
```

### D-Bus Connection Failed

```bash
# Ensure daemon was started with --dbus flag
make slack-daemon-bg  # Uses --dbus automatically

# Check D-Bus session
echo $DBUS_SESSION_BUS_ADDRESS
```

### No Response to Messages

1. Check the bot is monitoring the right channels (see logs)
2. Verify your user mapping in config.json
3. Check pending messages: `make slack-pending`
4. Review logs: `make slack-daemon-logs`

## Safety Guidelines

- Never execute destructive operations without confirmation
- Production actions require explicit user approval
- Always show what you're about to do before doing it
- Log all actions for audit trail

## Related

- [investigate_slack_alert Skill](../skills/investigate_slack_alert.md)
- [slack_daemon_control Skill](../skills/slack_daemon_control.md)
- [Slack Tool Module](../tool-modules/slack.md)
