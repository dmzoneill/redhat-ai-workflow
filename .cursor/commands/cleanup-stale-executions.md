# Cleanup Stale Executions

Cleans up stale skill executions from the skill_execution.json file.

## Instructions

```text
skill_run("cleanup_stale_executions", '{}')
```

## What It Does

Cleans up stale skill executions from the skill_execution.json file.

A skill execution is considered stale if:
- It's been "running" for more than 30 minutes, OR
- It's been "running" for more than 10 minutes with no recent events

Completed executions older than 5 minutes are also removed to keep the file small.

This skill is designed to run periodically via cron to prevent the execution
tracking file from growing unbounded and to clear stuck executions.
