---
name: workflow-health-check
description: "Perform a comprehensive system health check across all workflow services."
arguments:
  - name: fix_issues
  - name: verbose
  - name: check_remote
---
# Workflow Health Check

Perform a comprehensive system health check across all workflow services.

## Instructions

```text
skill_run("workflow_health_check", '{"fix_issues": "", "verbose": "", "check_remote": ""}')
```

## What It Does

Perform a comprehensive system health check across all workflow services.

This skill checks:
- Systemd service status
- Journal logs for errors
- Ollama AI service health
- Cron job configuration
- Podman container status
- SQLite database integrity
- HTTP endpoint health
- SSH connectivity
- InScope authentication
- System time and hostname
- Local workflow checks

Uses: systemctl_status, systemctl_is_active, systemctl_list_units,
journalctl_unit, ollama_status, ollama_test, cron_list,
cron_status, podman_ps, sqlite_query, sqlite_tables, curl_get,
ssh_test, inscope_auth_status, timedatectl_status, hostnamectl_status,
workflow_run_local_checks

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `fix_issues` | Attempt to fix detected issues automatically | No |
| `verbose` | Show verbose output for all checks | No |
| `check_remote` | Include remote host checks via SSH | No |
