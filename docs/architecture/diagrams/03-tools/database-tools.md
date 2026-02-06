# Database Tools

> SQLite, PostgreSQL, and MySQL integration modules

## Diagram

```mermaid
classDiagram
    class SQLiteBasic {
        +sqlite_query(db, sql): list
        +sqlite_tables(db): list
        +sqlite_schema(db, table): dict
        +sqlite_execute(db, sql): dict
    }

    class PostgresBasic {
        +postgres_query(sql): list
        +postgres_tables(): list
        +postgres_schema(table): dict
        +postgres_execute(sql): dict
    }

    class MySQLBasic {
        +mysql_query(sql): list
        +mysql_tables(): list
        +mysql_schema(table): dict
        +mysql_execute(sql): dict
    }

    class DatabaseAdapter {
        <<interface>>
        +connect()
        +query(sql): list
        +execute(sql): dict
        +close()
    }

    SQLiteBasic ..|> DatabaseAdapter
    PostgresBasic ..|> DatabaseAdapter
    MySQLBasic ..|> DatabaseAdapter
```

## Query Flow

```mermaid
sequenceDiagram
    participant Tool as Database Tool
    participant Adapter as DB Adapter
    participant Pool as Connection Pool
    participant DB as Database

    Tool->>Adapter: query(sql)
    Adapter->>Pool: Get connection
    Pool-->>Adapter: Connection
    Adapter->>DB: Execute SQL
    DB-->>Adapter: Result set
    Adapter->>Pool: Return connection
    Adapter-->>Tool: Formatted results
```

## Components

| Module | File | Description |
|--------|------|-------------|
| aa_sqlite | `tool_modules/aa_sqlite/` | SQLite operations |
| aa_postgres | `tool_modules/aa_postgres/` | PostgreSQL operations |
| aa_mysql | `tool_modules/aa_mysql/` | MySQL operations |

## Tool Summary

| Tool | Module | Description |
|------|--------|-------------|
| `sqlite_query` | sqlite | Execute SELECT query |
| `sqlite_tables` | sqlite | List tables |
| `sqlite_schema` | sqlite | Get table schema |
| `sqlite_execute` | sqlite | Execute INSERT/UPDATE/DELETE |
| `postgres_query` | postgres | Execute SELECT query |
| `mysql_query` | mysql | Execute SELECT query |

## SQLite Usage

```mermaid
flowchart TB
    subgraph LocalDBs[Local SQLite Databases]
        CURSOR[Cursor IDE DB<br/>~/.cursor/...]
        NOTES[Meeting Notes<br/>notes.db]
        CACHE[Tool Cache<br/>cache.db]
    end

    subgraph Tools[SQLite Tools]
        QUERY[sqlite_query]
        TABLES[sqlite_tables]
        SCHEMA[sqlite_schema]
    end

    CURSOR --> QUERY
    NOTES --> QUERY
    CACHE --> QUERY
    QUERY --> TABLES
    TABLES --> SCHEMA
```

## Configuration

```json
{
  "databases": {
    "sqlite": {
      "allowed_paths": [
        "~/.cursor/",
        "~/.config/aa-workflow/"
      ]
    },
    "postgres": {
      "host": "localhost",
      "port": 5432,
      "database": "analytics",
      "user_env": "POSTGRES_USER",
      "password_env": "POSTGRES_PASSWORD"
    },
    "mysql": {
      "host": "localhost",
      "port": 3306,
      "database": "app",
      "user_env": "MYSQL_USER",
      "password_env": "MYSQL_PASSWORD"
    }
  }
}
```

## Safety Rules

| Operation | Safety Level | Notes |
|-----------|--------------|-------|
| SELECT | Safe | Read-only |
| INSERT | Caution | Modifies data |
| UPDATE | Caution | Modifies data |
| DELETE | Dangerous | Requires confirmation |
| DROP | Dangerous | Requires confirmation |
| TRUNCATE | Dangerous | Requires confirmation |

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Session Daemon](../02-services/session-daemon.md)
- [Meet Daemon](../02-services/meet-daemon.md)
