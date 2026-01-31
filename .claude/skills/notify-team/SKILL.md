---
name: notify-team
description: Send notifications to Slack channels for key workflow events
license: MIT
compatibility: opencode
metadata:
  version: "1.1"
  source: notify_team.yaml
  executable: "true"
---

# notify_team

Send notifications to Slack channels for key workflow events.
Uses consistent templates for uniform, predictable messages.

## Templates Available

**mr_ready** - MR ready for review
```json
{"template": "mr_ready", "template_data": {"mr_id": "1495", "title": "fix(deps): update urllib3", "url": "https://gitlab.../1495", "issue_key": "AAP-62128"}}
```

**deployment** - Deployment status
```json
{"template": "deployment", "template_data": {"environment": "stage", "namespace": "ephemeral-xxx", "status": "success", "duration": "5m"}}
```

**alert** - Alert notification
```json
{"template": "alert", "template_data": {"alert_name": "HighCPU", "severity": "warning", "environment": "prod"}}
```

**release** - Release announcement
```json
{"template": "release", "template_data": {"version": "1.2.3", "environments": ["stage", "prod"]}}
```

**cve_fix** - Security fix notification
```json
{"template": "cve_fix", "template_data": {"cve_id": "CVE-2025-66471", "package": "urllib3", "version": "2.6.3", "mr_url": "https://..."}}
```

**generic** - Plain message with emoji (default)

## Quick Examples

Simple message:
```
skill_run("notify_team", '{"message": "Build complete"}')
```

MR notification:
```
skill_run("notify_team", '{"message": "", "template": "mr_ready", "template_data": {"mr_id": "1495", "title": "fix: update deps", "url": "https://...", "issue_key": "AAP-62128"}}')
```

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("notify_team", '{
  "message": "example-message",
  "channel": "example-channel",
  "type": "info",
  "mention": "example-mention",
  "thread_ts": "example-thread_ts",
  "context": "example-context",
  "template": "example-template",
  "template_data": "example-template_data"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load slack persona for Slack notification tools**
2. **Check for known Slack issues before starting**
3. **Initialize failure tracking**
4. **Load Slack configuration from config.json**
5. **List available Slack channels**
6. **Find the target channel**
7. **Get Slack user info for mentions**
8. **Parse user info for mention**
9. **Format the Slack message using templates for consistent notifications**
10. **Post the message to Slack**
11. **Parse post result**
12. **Search for code related to the notification context**
13. **Parse context code search results**
14. **Log notification to session**
15. **Track notifications for patterns**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `message` | string | Yes | `-` | Message to send |
| `channel` | string | No | `-` | Slack channel name or ID (defaults to team channel from config.json) |
| `type` | string | No | `info` | Message type: 'info', 'success', 'warning', 'error', 'deployment', 'release' |
| `mention` | string | No | `-` | User to mention (Slack username or email) |
| `thread_ts` | string | No | `-` | Thread timestamp to reply to (for threaded messages) |
| `context` | string | No | `-` | Additional context (e.g., MR ID, namespace, issue key) |
| `template` | string | No | `-` | Message template to use. If not specified, auto-detects from 'type'. Available templates:   - mr_ready: MR ready for review (requires: mr_id, title, url, issue_key)   - mr_merged: MR merged notification (requires: mr_id, title, url)   - deployment: Deployment status (requires: environment, namespace, status)   - alert: Alert notification (requires: alert_name, severity, environment)   - release: Release announcement (requires: version, environments)   - cve_fix: CVE fix notification (requires: cve_id, package, version, mr_url)   - generic: Plain message with emoji (default)  |
| `template_data` | object | No | `-` | Data for the template as JSON object. Fields depend on template:   mr_ready: {"mr_id": "1495", "title": "fix: ...", "url": "https://...", "issue_key": "AAP-12345"}   deployment: {"environment": "stage", "namespace": "ephemeral-xxx", "status": "success", "duration": "5m"}   alert: {"alert_name": "HighCPU", "severity": "warning", "environment": "prod", "runbook": "https://..."}   release: {"version": "1.2.3", "environments": ["stage", "prod"], "changelog": "..."}   cve_fix: {"cve_id": "CVE-2025-66471", "package": "urllib3", "version": "2.6.3", "mr_url": "https://..."}  |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the notify_team skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("notify_team", '{
  "message": "example-message",
  "channel": "example-channel",
  "type": "info",
  "mention": "example-mention",
  "thread_ts": "example-thread_ts",
  "context": "example-context",
  "template": "example-template",
  "template_data": "example-template_data"
}')
```

### Via Command (if configured)

```
/notify-team
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `memory_session_log`
- `persona_load`
- `slack_get_user`
- `slack_list_channels`
- `slack_send_message`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/notify_team.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/notify_team.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
