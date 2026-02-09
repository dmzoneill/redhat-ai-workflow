# Schedule Cron Jobs

Manage scheduled automation jobs for the workflow system.

## Instructions

```text
skill_run("schedule_cron_jobs", '{"action": "$ACTION", "job_name": "", "schedule": "", "skill_name": ""}')
```

## What It Does

Manage scheduled automation jobs for the workflow system.

Supports:
- List all scheduled jobs
- Add new cron jobs (skill-based or command-based)
- Remove existing jobs
- Enable/disable jobs
- Run jobs immediately
- View job history and status

Uses: cron_list, cron_add, cron_remove, cron_enable, cron_run_now,
cron_status, cron_notifications, systemctl_status, systemctl_restart,
journalctl_unit

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `action` | Action to perform | Yes |
| `job_name` | Name of the cron job (required for add/remove/enable/disable/run) | No |
| `schedule` | Cron schedule expression (required for add, e.g., '0 9 * * *' for 9am daily) | No |
| `skill_name` | Skill to run on schedule (required for add) | No |
