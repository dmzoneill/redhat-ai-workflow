"""PostgreSQL tool definitions - Database management.

Provides:
Query tools:
- psql_query: Execute SQL query
- psql_databases: List databases
- psql_tables: List tables in database
- psql_describe: Describe table structure
- psql_schemas: List schemas

Admin tools:
- psql_activity: Show database activity
- psql_locks: Show current locks
- psql_size: Show database/table sizes
- psql_connections: Show connection info

Data tools:
- pg_dump: Dump database to SQL
- pg_dumpall_globals: Dump global objects (roles, tablespaces)
"""

import logging
import os

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)


def _get_psql_env(password: str = "") -> dict:
    """Get environment for psql commands."""
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    return env


def _build_psql_cmd(
    host: str = "",
    port: int = 0,
    user: str = "",
    database: str = "",
) -> list:
    """Build psql command with connection options."""
    cmd = ["psql"]
    if host:
        cmd.extend(["-h", host])
    if port:
        cmd.extend(["-p", str(port)])
    if user:
        cmd.extend(["-U", user])
    if database:
        cmd.extend(["-d", database])
    return cmd


@auto_heal()
async def _psql_query_impl(
    query: str,
    database: str = "postgres",
    host: str = "localhost",
    port: int = 5432,
    user: str = "",
    password: str = "",
    expanded: bool = False,
) -> str:
    """Execute SQL query."""
    cmd = _build_psql_cmd(host, port, user, database)
    cmd.extend(["-c", query])
    if expanded:
        cmd.append("-x")

    success, output = await run_cmd(cmd, timeout=120, env=_get_psql_env(password))
    if success:
        return f"## Query Result\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Query failed: {output}"


@auto_heal()
async def _psql_databases_impl(
    host: str = "localhost",
    port: int = 5432,
    user: str = "",
    password: str = "",
) -> str:
    """List databases."""
    cmd = _build_psql_cmd(host, port, user, "postgres")
    cmd.extend(["-c", "\\l"])

    success, output = await run_cmd(cmd, timeout=30, env=_get_psql_env(password))
    if success:
        return f"## Databases\n\n```\n{output}\n```"
    return f"❌ Failed to list databases: {output}"


@auto_heal()
async def _psql_tables_impl(
    database: str,
    schema: str = "public",
    host: str = "localhost",
    port: int = 5432,
    user: str = "",
    password: str = "",
) -> str:
    """List tables in database."""
    cmd = _build_psql_cmd(host, port, user, database)
    cmd.extend(["-c", f"\\dt {schema}.*"])

    success, output = await run_cmd(cmd, timeout=30, env=_get_psql_env(password))
    if success:
        return f"## Tables in {database}.{schema}\n\n```\n{output}\n```"
    return f"❌ Failed to list tables: {output}"


@auto_heal()
async def _psql_describe_impl(
    table: str,
    database: str,
    host: str = "localhost",
    port: int = 5432,
    user: str = "",
    password: str = "",
) -> str:
    """Describe table structure."""
    cmd = _build_psql_cmd(host, port, user, database)
    cmd.extend(["-c", f"\\d+ {table}"])

    success, output = await run_cmd(cmd, timeout=30, env=_get_psql_env(password))
    if success:
        return f"## Table: {table}\n\n```\n{output}\n```"
    return f"❌ Failed to describe table: {output}"


@auto_heal()
async def _psql_schemas_impl(
    database: str,
    host: str = "localhost",
    port: int = 5432,
    user: str = "",
    password: str = "",
) -> str:
    """List schemas."""
    cmd = _build_psql_cmd(host, port, user, database)
    cmd.extend(["-c", "\\dn+"])

    success, output = await run_cmd(cmd, timeout=30, env=_get_psql_env(password))
    if success:
        return f"## Schemas in {database}\n\n```\n{output}\n```"
    return f"❌ Failed to list schemas: {output}"


@auto_heal()
async def _psql_activity_impl(
    database: str = "",
    host: str = "localhost",
    port: int = 5432,
    user: str = "",
    password: str = "",
) -> str:
    """Show database activity."""
    query = """
    SELECT pid, usename, datname, state, query_start, query
    FROM pg_stat_activity
    WHERE state != 'idle'
    ORDER BY query_start;
    """
    cmd = _build_psql_cmd(host, port, user, database or "postgres")
    cmd.extend(["-c", query])

    success, output = await run_cmd(cmd, timeout=30, env=_get_psql_env(password))
    if success:
        return f"## Database Activity\n\n```\n{output}\n```"
    return f"❌ Failed to get activity: {output}"


@auto_heal()
async def _psql_locks_impl(
    database: str = "",
    host: str = "localhost",
    port: int = 5432,
    user: str = "",
    password: str = "",
) -> str:
    """Show current locks."""
    query = """
    SELECT l.pid, l.locktype, l.mode, l.granted, a.usename, a.query
    FROM pg_locks l
    JOIN pg_stat_activity a ON l.pid = a.pid
    WHERE NOT l.granted OR l.locktype = 'relation'
    ORDER BY l.pid;
    """
    cmd = _build_psql_cmd(host, port, user, database or "postgres")
    cmd.extend(["-c", query])

    success, output = await run_cmd(cmd, timeout=30, env=_get_psql_env(password))
    if success:
        return f"## Database Locks\n\n```\n{output}\n```"
    return f"❌ Failed to get locks: {output}"


@auto_heal()
async def _psql_size_impl(
    database: str,
    host: str = "localhost",
    port: int = 5432,
    user: str = "",
    password: str = "",
) -> str:
    """Show database/table sizes."""
    query = """
    SELECT
        schemaname,
        tablename,
        pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) as total_size
    FROM pg_tables
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC
    LIMIT 20;
    """
    cmd = _build_psql_cmd(host, port, user, database)
    cmd.extend(["-c", query])

    success, output = await run_cmd(cmd, timeout=30, env=_get_psql_env(password))
    if success:
        return f"## Table Sizes in {database}\n\n```\n{output}\n```"
    return f"❌ Failed to get sizes: {output}"


@auto_heal()
async def _psql_connections_impl(
    host: str = "localhost",
    port: int = 5432,
    user: str = "",
    password: str = "",
) -> str:
    """Show connection info."""
    query = """
    SELECT datname, usename, client_addr, state, COUNT(*)
    FROM pg_stat_activity
    GROUP BY datname, usename, client_addr, state
    ORDER BY datname, count DESC;
    """
    cmd = _build_psql_cmd(host, port, user, "postgres")
    cmd.extend(["-c", query])

    success, output = await run_cmd(cmd, timeout=30, env=_get_psql_env(password))
    if success:
        return f"## Connections\n\n```\n{output}\n```"
    return f"❌ Failed to get connections: {output}"


@auto_heal()
async def _pg_dump_impl(
    database: str,
    host: str = "localhost",
    port: int = 5432,
    user: str = "",
    password: str = "",
    schema_only: bool = False,
    table: str = "",
) -> str:
    """Dump database to SQL."""
    cmd = ["pg_dump"]
    if host:
        cmd.extend(["-h", host])
    if port:
        cmd.extend(["-p", str(port)])
    if user:
        cmd.extend(["-U", user])
    if schema_only:
        cmd.append("--schema-only")
    if table:
        cmd.extend(["-t", table])
    cmd.append(database)

    success, output = await run_cmd(cmd, timeout=300, env=_get_psql_env(password))
    if success:
        return f"## SQL Dump: {database}\n\n```sql\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Dump failed: {output}"


def register_tools(server: FastMCP) -> int:
    """Register PostgreSQL tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def psql_query(
        query: str,
        database: str = "postgres",
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """Execute SQL query.

        Args:
            query: SQL query to execute
            database: Database name
            host: PostgreSQL host
            user: PostgreSQL user
            password: PostgreSQL password
        """
        return await _psql_query_impl(query, database, host, 5432, user, password)

    @auto_heal()
    @registry.tool()
    async def psql_databases(
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """List databases.

        Args:
            host: PostgreSQL host
            user: PostgreSQL user
            password: PostgreSQL password
        """
        return await _psql_databases_impl(host, 5432, user, password)

    @auto_heal()
    @registry.tool()
    async def psql_tables(
        database: str,
        schema: str = "public",
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """List tables in database.

        Args:
            database: Database name
            schema: Schema name
            host: PostgreSQL host
            user: PostgreSQL user
            password: PostgreSQL password
        """
        return await _psql_tables_impl(database, schema, host, 5432, user, password)

    @auto_heal()
    @registry.tool()
    async def psql_describe(
        table: str,
        database: str,
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """Describe table structure.

        Args:
            table: Table name
            database: Database name
            host: PostgreSQL host
            user: PostgreSQL user
            password: PostgreSQL password
        """
        return await _psql_describe_impl(table, database, host, 5432, user, password)

    @auto_heal()
    @registry.tool()
    async def psql_schemas(
        database: str,
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """List schemas.

        Args:
            database: Database name
            host: PostgreSQL host
            user: PostgreSQL user
            password: PostgreSQL password
        """
        return await _psql_schemas_impl(database, host, 5432, user, password)

    @auto_heal()
    @registry.tool()
    async def psql_activity(
        database: str = "",
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """Show database activity.

        Args:
            database: Database name (optional)
            host: PostgreSQL host
            user: PostgreSQL user
            password: PostgreSQL password
        """
        return await _psql_activity_impl(database, host, 5432, user, password)

    @auto_heal()
    @registry.tool()
    async def psql_locks(
        database: str = "",
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """Show current locks.

        Args:
            database: Database name (optional)
            host: PostgreSQL host
            user: PostgreSQL user
            password: PostgreSQL password
        """
        return await _psql_locks_impl(database, host, 5432, user, password)

    @auto_heal()
    @registry.tool()
    async def psql_size(
        database: str,
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """Show database/table sizes.

        Args:
            database: Database name
            host: PostgreSQL host
            user: PostgreSQL user
            password: PostgreSQL password
        """
        return await _psql_size_impl(database, host, 5432, user, password)

    @auto_heal()
    @registry.tool()
    async def psql_connections(
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """Show connection info.

        Args:
            host: PostgreSQL host
            user: PostgreSQL user
            password: PostgreSQL password
        """
        return await _psql_connections_impl(host, 5432, user, password)

    @auto_heal()
    @registry.tool()
    async def pg_dump(
        database: str,
        host: str = "localhost",
        user: str = "",
        password: str = "",
        schema_only: bool = False,
        table: str = "",
    ) -> str:
        """Dump database to SQL.

        Args:
            database: Database name
            host: PostgreSQL host
            user: PostgreSQL user
            password: PostgreSQL password
            schema_only: Dump schema only (no data)
            table: Specific table to dump
        """
        return await _pg_dump_impl(database, host, 5432, user, password, schema_only, table)

    return registry.count
