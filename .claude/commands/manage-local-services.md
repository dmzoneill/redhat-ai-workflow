---
name: manage-local-services
description: "Manage workflow daemon services running locally."
arguments:
  - name: action
    required: true
  - name: service
---
# Manage Local Services

Manage workflow daemon services running locally.

## Instructions

```text
skill_run("manage_local_services", '{"action": "$ACTION", "service": ""}')
```

## What It Does

Manage workflow daemon services running locally.

Supports start, stop, restart, and status actions for:
- MCP server (aa-workflow-mcp)
- SLOP API gateway (aa-workflow-slop)
- Slack daemon (aa-workflow-slack)
- Ollama inference server
- Scheduler (cron jobs)
- All services at once

Uses: systemctl_status, systemctl_start, systemctl_stop, systemctl_restart,
systemctl_is_active, systemctl_list_units, systemctl_enable, systemctl_disable,
journalctl_unit, journalctl_logs, systemctl_daemon_reload, ollama_status,
cron_list, cron_status

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `action` | Action to perform on services | Yes |
| `service` | Service to manage (default: all) (default: all) | No |
