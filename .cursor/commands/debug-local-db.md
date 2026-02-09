# Debug Local Db

Debug database issues in local or ephemeral environments.

## Instructions

```text
skill_run("debug_local_db", '{"database": "", "issue_description": "", "dump_schema": ""}')
```

## What It Does

Debug database issues in local or ephemeral environments.

This skill inspects:
- PostgreSQL connections, locks, and activity
- Database size and table structure
- SQLite database health
- Podman container logs for database services
- Schema dumps for analysis

Uses Podman for container operations (not Docker).

Uses: psql_query, psql_activity, psql_locks, psql_size, psql_connections,
psql_tables, psql_describe, psql_schemas, pg_dump, sqlite_query,
sqlite_tables, sqlite_schema, sqlite_vacuum, podman_exec, podman_logs

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `database` | Database target (local, ephemeral, workflow) (default: local) | No |
| `issue_description` | Description of the database issue to investigate | No |
| `dump_schema` | Dump full database schema for analysis | No |
