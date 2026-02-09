# Mysql Debug

Debug MySQL or MariaDB database issues.

## Instructions

```text
skill_run("mysql_debug", '{"host": "", "database": "", "issue_description": "", "check_processes": ""}')
```

## What It Does

Debug MySQL or MariaDB database issues.

This skill inspects:
- Database list and table structure
- Active processes and connections
- Server status and variables
- Table definitions and schemas
- Slow queries and lock contention

Uses: mysql_query, mysql_databases, mysql_tables, mysql_describe,
mysql_show_create_table, mysql_processlist, mysql_status

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `host` | MySQL host to connect to (default: localhost) | No |
| `database` | Database name to inspect | No |
| `issue_description` | Description of the database issue to investigate | No |
| `check_processes` | Include process list and connection analysis (default: True) | No |
