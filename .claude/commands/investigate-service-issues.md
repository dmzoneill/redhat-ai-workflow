---
name: investigate-service-issues
description: "Debug systemd service failures and investigate issues."
arguments:
  - name: service_name
  - name: since
  - name: auto_restart
  - name: check_all_failed
---
# Investigate Service Issues

Debug systemd service failures and investigate issues.

## Instructions

```text
skill_run("investigate_service_issues", '{"service_name": "", "since": "", "auto_restart": "", "check_all_failed": ""}')
```

## What It Does

Debug systemd service failures and investigate issues.

Features:
- Check service status and health
- Analyze journal logs for errors
- Check boot-level issues
- List all failed units
- Auto-restart failed services if enabled
- Check system info (hostname, time sync)

Uses: systemctl_status, systemctl_is_active, systemctl_is_enabled,
systemctl_list_units, systemctl_list_unit_files, journalctl_unit,
journalctl_logs, journalctl_boot, systemctl_daemon_reload,
systemctl_restart, hostnamectl_status, timedatectl_status, ollama_status

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `service_name` | Specific service to investigate (e.g., aa-workflow-mcp). Leave empty to check all failed. | No |
| `since` | Time window for log analysis (e.g., 1h, 30m, 1d) (default: 1h) | No |
| `auto_restart` | Automatically restart failed services | No |
| `check_all_failed` | Check all failed systemd units (default: True) | No |
