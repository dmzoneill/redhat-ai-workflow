"""SQLite tool definitions - SQLite database management.

Provides:
Query tools:
- sqlite_query: Execute SQL query
- sqlite_tables: List tables in database
- sqlite_schema: Show table schema
- sqlite_describe: Describe table structure

Data tools:
- sqlite_dump: Dump database to SQL
- sqlite_import_csv: Import CSV into table

Database tools:
- sqlite_databases: List databases (attached)
- sqlite_vacuum: Optimize database
- sqlite_integrity_check: Check database integrity
"""

import logging
from pathlib import Path

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)


@auto_heal()
async def _sqlite_query_impl(
    database: str,
    query: str,
    mode: str = "column",
    headers: bool = True,
) -> str:
    """Execute SQL query."""
    db_path = Path(database).expanduser()
    if not db_path.exists():
        return f"❌ Database not found: {database}"

    cmd = ["sqlite3", str(db_path)]
    if headers:
        cmd.append("-header")
    cmd.extend([f"-{mode}", query])

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        return f"## Query Result\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Query failed: {output}"


@auto_heal()
async def _sqlite_tables_impl(database: str) -> str:
    """List tables in database."""
    db_path = Path(database).expanduser()
    if not db_path.exists():
        return f"❌ Database not found: {database}"

    cmd = ["sqlite3", str(db_path), ".tables"]

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Tables in {db_path.name}\n\n```\n{output}\n```"
    return f"❌ Failed to list tables: {output}"


@auto_heal()
async def _sqlite_schema_impl(database: str, table: str = "") -> str:
    """Show table schema."""
    db_path = Path(database).expanduser()
    if not db_path.exists():
        return f"❌ Database not found: {database}"

    query = f".schema {table}" if table else ".schema"
    cmd = ["sqlite3", str(db_path), query]

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Schema\n\n```sql\n{output}\n```"
    return f"❌ Failed to get schema: {output}"


@auto_heal()
async def _sqlite_describe_impl(database: str, table: str) -> str:
    """Describe table structure."""
    db_path = Path(database).expanduser()
    if not db_path.exists():
        return f"❌ Database not found: {database}"

    cmd = ["sqlite3", str(db_path), "-header", "-column", f"PRAGMA table_info({table});"]

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Table: {table}\n\n```\n{output}\n```"
    return f"❌ Failed to describe table: {output}"


@auto_heal()
async def _sqlite_dump_impl(database: str, table: str = "") -> str:
    """Dump database to SQL."""
    db_path = Path(database).expanduser()
    if not db_path.exists():
        return f"❌ Database not found: {database}"

    query = f".dump {table}" if table else ".dump"
    cmd = ["sqlite3", str(db_path), query]

    success, output = await run_cmd(cmd, timeout=120)
    if success:
        return f"## SQL Dump\n\n```sql\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to dump database: {output}"


@auto_heal()
async def _sqlite_import_csv_impl(
    database: str,
    table: str,
    csv_file: str,
    skip_header: bool = True,
) -> str:
    """Import CSV into table."""
    db_path = Path(database).expanduser()
    csv_path = Path(csv_file).expanduser()

    if not csv_path.exists():
        return f"❌ CSV file not found: {csv_file}"

    commands = [".mode csv"]
    if skip_header:
        commands.append(".headers on")
    commands.append(f".import {csv_path} {table}")

    cmd = ["sqlite3", str(db_path)] + commands

    success, output = await run_cmd(cmd, timeout=120)
    if success:
        return f"✅ Imported {csv_file} into {table}"
    return f"❌ Import failed: {output}"


@auto_heal()
async def _sqlite_vacuum_impl(database: str) -> str:
    """Optimize database."""
    db_path = Path(database).expanduser()
    if not db_path.exists():
        return f"❌ Database not found: {database}"

    cmd = ["sqlite3", str(db_path), "VACUUM;"]

    success, output = await run_cmd(cmd, timeout=300)
    if success:
        return f"✅ Database vacuumed: {database}"
    return f"❌ Vacuum failed: {output}"


@auto_heal()
async def _sqlite_integrity_check_impl(database: str) -> str:
    """Check database integrity."""
    db_path = Path(database).expanduser()
    if not db_path.exists():
        return f"❌ Database not found: {database}"

    cmd = ["sqlite3", str(db_path), "PRAGMA integrity_check;"]

    success, output = await run_cmd(cmd, timeout=120)
    if success:
        if "ok" in output.lower():
            return f"✅ Database integrity OK: {database}"
        return f"⚠️ Integrity issues found:\n\n```\n{output}\n```"
    return f"❌ Integrity check failed: {output}"


@auto_heal()
async def _sqlite_count_impl(database: str, table: str) -> str:
    """Count rows in table."""
    db_path = Path(database).expanduser()
    if not db_path.exists():
        return f"❌ Database not found: {database}"

    cmd = ["sqlite3", str(db_path), f"SELECT COUNT(*) FROM {table};"]

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        count = output.strip()
        return f"**{table}**: {count} rows"
    return f"❌ Count failed: {output}"


def register_tools(server: FastMCP) -> int:
    """Register SQLite tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def sqlite_query(
        database: str,
        query: str,
        mode: str = "column",
    ) -> str:
        """Execute SQL query.

        Args:
            database: Path to SQLite database file
            query: SQL query to execute
            mode: Output mode (column, csv, json, table)
        """
        return await _sqlite_query_impl(database, query, mode)

    @auto_heal()
    @registry.tool()
    async def sqlite_tables(database: str) -> str:
        """List tables in database.

        Args:
            database: Path to SQLite database file
        """
        return await _sqlite_tables_impl(database)

    @auto_heal()
    @registry.tool()
    async def sqlite_schema(database: str, table: str = "") -> str:
        """Show table schema.

        Args:
            database: Path to SQLite database file
            table: Table name (optional, all tables if empty)
        """
        return await _sqlite_schema_impl(database, table)

    @auto_heal()
    @registry.tool()
    async def sqlite_describe(database: str, table: str) -> str:
        """Describe table structure.

        Args:
            database: Path to SQLite database file
            table: Table name
        """
        return await _sqlite_describe_impl(database, table)

    @auto_heal()
    @registry.tool()
    async def sqlite_dump(database: str, table: str = "") -> str:
        """Dump database to SQL.

        Args:
            database: Path to SQLite database file
            table: Table name (optional, all tables if empty)
        """
        return await _sqlite_dump_impl(database, table)

    @auto_heal()
    @registry.tool()
    async def sqlite_vacuum(database: str) -> str:
        """Optimize database.

        Args:
            database: Path to SQLite database file
        """
        return await _sqlite_vacuum_impl(database)

    @auto_heal()
    @registry.tool()
    async def sqlite_integrity_check(database: str) -> str:
        """Check database integrity.

        Args:
            database: Path to SQLite database file
        """
        return await _sqlite_integrity_check_impl(database)

    @auto_heal()
    @registry.tool()
    async def sqlite_count(database: str, table: str) -> str:
        """Count rows in table.

        Args:
            database: Path to SQLite database file
            table: Table name
        """
        return await _sqlite_count_impl(database, table)

    return registry.count
