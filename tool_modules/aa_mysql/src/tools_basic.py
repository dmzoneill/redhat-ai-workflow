"""MySQL/MariaDB tool definitions - Database management.

Provides:
Query tools:
- mysql_query: Execute SQL query
- mysql_databases: List databases
- mysql_tables: List tables in database
- mysql_describe: Describe table structure
- mysql_show_create_table: Show CREATE TABLE statement

Admin tools:
- mysql_processlist: Show running processes
- mysql_status: Show server status
- mysql_variables: Show server variables

Data tools:
- mysql_dump: Dump database to SQL
- mysql_import: Import SQL file
"""

import logging

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)


def _build_mysql_cmd(
    host: str = "",
    port: int = 0,
    user: str = "",
    password: str = "",
    database: str = "",
) -> list:
    """Build mysql command with connection options."""
    cmd = ["mysql"]
    if host:
        cmd.extend(["-h", host])
    if port:
        cmd.extend(["-P", str(port)])
    if user:
        cmd.extend(["-u", user])
    if password:
        cmd.extend([f"-p{password}"])
    if database:
        cmd.append(database)
    return cmd


@auto_heal()
async def _mysql_query_impl(
    query: str,
    database: str = "",
    host: str = "localhost",
    port: int = 3306,
    user: str = "",
    password: str = "",
    vertical: bool = False,
) -> str:
    """Execute SQL query."""
    cmd = _build_mysql_cmd(host, port, user, password, database)
    cmd.extend(["-e", query])
    if vertical:
        cmd.append("-E")

    success, output = await run_cmd(cmd, timeout=120)
    if success:
        return f"## Query Result\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Query failed: {output}"


@auto_heal()
async def _mysql_databases_impl(
    host: str = "localhost",
    port: int = 3306,
    user: str = "",
    password: str = "",
) -> str:
    """List databases."""
    cmd = _build_mysql_cmd(host, port, user, password)
    cmd.extend(["-e", "SHOW DATABASES;"])

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Databases\n\n```\n{output}\n```"
    return f"❌ Failed to list databases: {output}"


@auto_heal()
async def _mysql_tables_impl(
    database: str,
    host: str = "localhost",
    port: int = 3306,
    user: str = "",
    password: str = "",
) -> str:
    """List tables in database."""
    cmd = _build_mysql_cmd(host, port, user, password, database)
    cmd.extend(["-e", "SHOW TABLES;"])

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Tables in {database}\n\n```\n{output}\n```"
    return f"❌ Failed to list tables: {output}"


@auto_heal()
async def _mysql_describe_impl(
    table: str,
    database: str,
    host: str = "localhost",
    port: int = 3306,
    user: str = "",
    password: str = "",
) -> str:
    """Describe table structure."""
    cmd = _build_mysql_cmd(host, port, user, password, database)
    cmd.extend(["-e", f"DESCRIBE {table};"])

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Table: {table}\n\n```\n{output}\n```"
    return f"❌ Failed to describe table: {output}"


@auto_heal()
async def _mysql_show_create_table_impl(
    table: str,
    database: str,
    host: str = "localhost",
    port: int = 3306,
    user: str = "",
    password: str = "",
) -> str:
    """Show CREATE TABLE statement."""
    cmd = _build_mysql_cmd(host, port, user, password, database)
    cmd.extend(["-e", f"SHOW CREATE TABLE {table}\\G"])

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## CREATE TABLE: {table}\n\n```sql\n{output}\n```"
    return f"❌ Failed to get CREATE TABLE: {output}"


@auto_heal()
async def _mysql_processlist_impl(
    host: str = "localhost",
    port: int = 3306,
    user: str = "",
    password: str = "",
) -> str:
    """Show running processes."""
    cmd = _build_mysql_cmd(host, port, user, password)
    cmd.extend(["-e", "SHOW FULL PROCESSLIST;"])

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Process List\n\n```\n{output}\n```"
    return f"❌ Failed to get process list: {output}"


@auto_heal()
async def _mysql_status_impl(
    host: str = "localhost",
    port: int = 3306,
    user: str = "",
    password: str = "",
) -> str:
    """Show server status."""
    cmd = _build_mysql_cmd(host, port, user, password)
    cmd.extend(["-e", "SHOW STATUS;"])

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Server Status\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to get status: {output}"


@auto_heal()
async def _mysql_variables_impl(
    pattern: str = "",
    host: str = "localhost",
    port: int = 3306,
    user: str = "",
    password: str = "",
) -> str:
    """Show server variables."""
    query = f"SHOW VARIABLES LIKE '{pattern}';" if pattern else "SHOW VARIABLES;"
    cmd = _build_mysql_cmd(host, port, user, password)
    cmd.extend(["-e", query])

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Server Variables\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to get variables: {output}"


@auto_heal()
async def _mysql_dump_impl(
    database: str,
    tables: str = "",
    host: str = "localhost",
    port: int = 3306,
    user: str = "",
    password: str = "",
    no_data: bool = False,
) -> str:
    """Dump database to SQL."""
    cmd = ["mysqldump"]
    if host:
        cmd.extend(["-h", host])
    if port:
        cmd.extend(["-P", str(port)])
    if user:
        cmd.extend(["-u", user])
    if password:
        cmd.extend([f"-p{password}"])
    if no_data:
        cmd.append("--no-data")
    cmd.append(database)
    if tables:
        cmd.extend(tables.split())

    success, output = await run_cmd(cmd, timeout=300)
    if success:
        return f"## SQL Dump: {database}\n\n```sql\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Dump failed: {output}"


def register_tools(server: FastMCP) -> int:
    """Register MySQL tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def mysql_query(
        query: str,
        database: str = "",
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """Execute SQL query.

        Args:
            query: SQL query to execute
            database: Database name
            host: MySQL host
            user: MySQL user
            password: MySQL password
        """
        return await _mysql_query_impl(query, database, host, 3306, user, password)

    @auto_heal()
    @registry.tool()
    async def mysql_databases(
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """List databases.

        Args:
            host: MySQL host
            user: MySQL user
            password: MySQL password
        """
        return await _mysql_databases_impl(host, 3306, user, password)

    @auto_heal()
    @registry.tool()
    async def mysql_tables(
        database: str,
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """List tables in database.

        Args:
            database: Database name
            host: MySQL host
            user: MySQL user
            password: MySQL password
        """
        return await _mysql_tables_impl(database, host, 3306, user, password)

    @auto_heal()
    @registry.tool()
    async def mysql_describe(
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
            host: MySQL host
            user: MySQL user
            password: MySQL password
        """
        return await _mysql_describe_impl(table, database, host, 3306, user, password)

    @auto_heal()
    @registry.tool()
    async def mysql_show_create_table(
        table: str,
        database: str,
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """Show CREATE TABLE statement.

        Args:
            table: Table name
            database: Database name
            host: MySQL host
            user: MySQL user
            password: MySQL password
        """
        return await _mysql_show_create_table_impl(table, database, host, 3306, user, password)

    @auto_heal()
    @registry.tool()
    async def mysql_processlist(
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """Show running processes.

        Args:
            host: MySQL host
            user: MySQL user
            password: MySQL password
        """
        return await _mysql_processlist_impl(host, 3306, user, password)

    @auto_heal()
    @registry.tool()
    async def mysql_status(
        host: str = "localhost",
        user: str = "",
        password: str = "",
    ) -> str:
        """Show server status.

        Args:
            host: MySQL host
            user: MySQL user
            password: MySQL password
        """
        return await _mysql_status_impl(host, 3306, user, password)

    @auto_heal()
    @registry.tool()
    async def mysql_dump(
        database: str,
        tables: str = "",
        host: str = "localhost",
        user: str = "",
        password: str = "",
        no_data: bool = False,
    ) -> str:
        """Dump database to SQL.

        Args:
            database: Database name
            tables: Space-separated table names (optional)
            host: MySQL host
            user: MySQL user
            password: MySQL password
            no_data: Dump schema only (no data)
        """
        return await _mysql_dump_impl(database, tables, host, 3306, user, password, no_data)

    return registry.count
