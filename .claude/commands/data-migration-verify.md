---
name: data-migration-verify
description: "Verify database migration correctness across different database types."
arguments:
  - name: db_type
    required: true
  - name: source_db
    required: true
  - name: target_db
    required: true
  - name: tables
  - name: migration_name
---
# Data Migration Verify

Verify database migration correctness across different database types.

## Instructions

```text
skill_run("data_migration_verify", '{"db_type": "$DB_TYPE", "source_db": "$SOURCE_DB", "target_db": "$TARGET_DB", "tables": "", "migration_name": ""}')
```

## What It Does

Verify database migration correctness across different database types.

This skill handles:
- Comparing source and target database schemas
- Verifying table structures match
- Running validation queries
- Checking row counts and data integrity
- Supporting PostgreSQL, MySQL, and SQLite
- Running queries inside Podman containers

Uses: psql_tables, psql_describe, psql_schemas, psql_query, psql_size,
mysql_tables, mysql_describe, mysql_show_create_table, mysql_query,
sqlite_tables, sqlite_schema, sqlite_describe, sqlite_query, podman_exec

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `db_type` | Database type (postgres|mysql|sqlite) | Yes |
| `source_db` | Source database connection string or path | Yes |
| `target_db` | Target database connection string or path | Yes |
| `tables` | Comma-separated list of tables to verify (all if empty) | No |
| `migration_name` | Name of the migration being verified | No |
