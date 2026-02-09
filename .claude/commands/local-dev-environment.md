---
name: local-dev-environment
description: "Start, stop, or check status of local development environment."
arguments:
  - name: repo
    required: true
  - name: action
  - name: run_migrations
  - name: health_check
---
# Local Dev Environment

Start, stop, or check status of local development environment.

## Instructions

```text
skill_run("local_dev_environment", '{"repo": "$REPO", "action": "", "run_migrations": "", "health_check": ""}')
```

## What It Does

Start, stop, or check status of local development environment.

Uses Podman Compose to manage containers for:
- Database (PostgreSQL)
- Application services
- Supporting infrastructure

Features:
- Start/stop/restart via Podman Compose
- Run database migrations
- Health check endpoints
- View container logs

Uses: podman_compose_up, podman_compose_down, podman_compose_status,
podman_ps, podman_logs, podman_exec, psql_query, psql_tables,
systemctl_is_active, curl_get, curl_timing

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `repo` | Path to repository with podman-compose.yaml | Yes |
| `action` | Action to perform (default: status) | No |
| `run_migrations` | Run database migrations after starting | No |
| `health_check` | Run health check after starting (default: True) | No |
