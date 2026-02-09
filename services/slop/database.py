"""
SQLite Database for Slop Bot Findings.

Stores and queries code quality findings with:
- Full-text search on descriptions
- Filtering by loop, category, severity, status
- Statistics aggregation
- Status updates (acknowledge, fix, false positive)

Usage:
    from services.slop.database import SlopDatabase

    db = SlopDatabase()
    await db.initialize()

    # Add a finding
    finding_id = await db.add_finding({
        "loop": "leaky",
        "file": "server/main.py",
        "line": 42,
        "category": "memory_leaks",
        "severity": "high",
        "description": "Unbounded cache",
        "suggestion": "Add max size limit",
    })

    # Query findings
    findings = await db.get_findings(filters={"severity": "high"})

    # Update status
    await db.update_status(finding_id, "acknowledged")
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from server.paths import AA_CONFIG_DIR

logger = logging.getLogger(__name__)


class SlopDatabase:
    """SQLite database for slop findings."""

    SCHEMA = """
    -- Findings table with unique constraint to prevent duplicates
    CREATE TABLE IF NOT EXISTS findings (
        id TEXT PRIMARY KEY,
        loop TEXT NOT NULL,
        file TEXT NOT NULL,
        line INTEGER DEFAULT 0,
        category TEXT NOT NULL,
        severity TEXT NOT NULL,
        description TEXT NOT NULL,
        suggestion TEXT DEFAULT '',
        tool TEXT DEFAULT '',
        raw_output TEXT DEFAULT '{}',
        detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'open',
        acknowledged_at TIMESTAMP,
        fixed_at TIMESTAMP,
        git_commit TEXT,
        -- Prevent duplicate findings for same file/line/category/description
        UNIQUE(file, line, category, description)
    );

    -- Indexes for common queries
    CREATE INDEX IF NOT EXISTS idx_findings_loop ON findings(loop);
    CREATE INDEX IF NOT EXISTS idx_findings_file ON findings(file);
    CREATE INDEX IF NOT EXISTS idx_findings_category ON findings(category);
    CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity);
    CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);
    CREATE INDEX IF NOT EXISTS idx_findings_detected ON findings(detected_at);
    CREATE INDEX IF NOT EXISTS idx_findings_last_seen ON findings(last_seen_at);

    -- Scan history table
    CREATE TABLE IF NOT EXISTS scan_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_type TEXT,
        loops_run TEXT,
        files_scanned INTEGER DEFAULT 0,
        findings_count INTEGER DEFAULT 0,
        duration_ms INTEGER DEFAULT 0,
        started_at TIMESTAMP,
        completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Loop run history
    CREATE TABLE IF NOT EXISTS loop_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loop_name TEXT NOT NULL,
        status TEXT NOT NULL,
        iterations INTEGER DEFAULT 0,
        findings_count INTEGER DEFAULT 0,
        duration_ms INTEGER DEFAULT 0,
        error TEXT,
        completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_loop_history_name ON loop_history(loop_name);
    CREATE INDEX IF NOT EXISTS idx_loop_history_completed ON loop_history(completed_at);
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the database.

        Args:
            db_path: Path to SQLite database file (default: ~/.config/aa-workflow/slop.db)
        """
        if db_path:
            self.db_path = Path(db_path)
        else:
            AA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            self.db_path = AA_CONFIG_DIR / "slop.db"

        self._db: Optional[aiosqlite.Connection] = None
        self._initialized = False

    async def initialize(self):
        """Initialize the database and create tables."""
        if self._initialized:
            return

        logger.info(f"Initializing slop database at {self.db_path}")

        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row

        # Create tables
        await self._db.executescript(self.SCHEMA)
        await self._db.commit()

        self._initialized = True
        logger.info("Slop database initialized")

    async def close(self):
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            self._initialized = False

    async def add_finding(self, finding: dict) -> str:
        """
        Add a finding to the database, or update last_seen_at if it already exists.

        Args:
            finding: Finding dict with required fields:
                - loop: Loop name that found this
                - file: File path
                - category: Issue category
                - severity: critical/high/medium/low
                - description: Issue description

        Returns:
            Finding ID
        """
        if not self._initialized:
            await self.initialize()

        finding_id = finding.get("id") or f"slop-{uuid.uuid4().hex[:12]}"

        raw_output = finding.get("raw_output", {})
        if isinstance(raw_output, dict):
            raw_output = json.dumps(raw_output)

        now = datetime.now().isoformat()

        # Use INSERT OR IGNORE to skip duplicates, then update last_seen_at
        # The UNIQUE constraint on (file, line, category, description) prevents duplicates
        await self._db.execute(
            """
            INSERT INTO findings
            (id, loop, file, line, category, severity, description,
             suggestion, tool, raw_output, detected_at, last_seen_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file, line, category, description) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                severity = excluded.severity,
                suggestion = excluded.suggestion
            """,
            (
                finding_id,
                finding.get("loop", "unknown"),
                finding.get("file", ""),
                finding.get("line", 0),
                finding.get("category", "unknown"),
                finding.get("severity", "medium"),
                finding.get("description", ""),
                finding.get("suggestion", ""),
                finding.get("tool", ""),
                raw_output,
                now,
                now,
                "open",
            ),
        )
        await self._db.commit()

        return finding_id

    async def add_findings(self, findings: list[dict]) -> list[str]:
        """Add multiple findings at once."""
        ids = []
        for finding in findings:
            finding_id = await self.add_finding(finding)
            ids.append(finding_id)
        return ids

    async def get_findings(
        self,
        filters: Optional[dict] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "detected_at DESC",
    ) -> list[dict]:
        """
        Get findings with optional filters.

        Args:
            filters: Dict of field -> value filters
            limit: Maximum results
            offset: Offset for pagination
            order_by: SQL ORDER BY clause

        Returns:
            List of finding dicts
        """
        if not self._initialized:
            await self.initialize()

        query = "SELECT * FROM findings"
        params = []

        if filters:
            conditions = []
            for field, value in filters.items():
                if field in ("loop", "file", "category", "severity", "status"):
                    conditions.append(f"{field} = ?")
                    params.append(value)
                elif field == "file_like":
                    conditions.append("file LIKE ?")
                    params.append(f"%{value}%")
                elif field == "description_like":
                    conditions.append("description LIKE ?")
                    params.append(f"%{value}%")

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

        # Whitelist allowed columns to prevent SQL injection
        ALLOWED_ORDER_COLUMNS = {
            "detected_at",
            "severity",
            "category",
            "status",
            "file",
            "loop",
            "detected_at DESC",
            "detected_at ASC",
            "severity DESC",
            "severity ASC",
            "category DESC",
            "category ASC",
            "status DESC",
            "status ASC",
            "file DESC",
            "file ASC",
        }
        if order_by not in ALLOWED_ORDER_COLUMNS:
            order_by = "detected_at DESC"
        query += f" ORDER BY {order_by} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_finding(self, finding_id: str) -> Optional[dict]:
        """Get a single finding by ID."""
        if not self._initialized:
            await self.initialize()

        async with self._db.execute(
            "SELECT * FROM findings WHERE id = ?",
            (finding_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_by_file(self, file_path: str) -> list[dict]:
        """Get all findings for a specific file."""
        return await self.get_findings(filters={"file": file_path})

    async def get_by_loop(self, loop_name: str) -> list[dict]:
        """Get all findings from a specific loop."""
        return await self.get_findings(filters={"loop": loop_name})

    async def get_by_category(self, category: str) -> list[dict]:
        """Get all findings of a specific category."""
        return await self.get_findings(filters={"category": category})

    async def update_status(self, finding_id: str, status: str) -> bool:
        """
        Update the status of a finding.

        Args:
            finding_id: Finding ID
            status: New status (open, acknowledged, fixed, false_positive)

        Returns:
            True if updated, False if not found
        """
        if not self._initialized:
            await self.initialize()

        timestamp_field = None
        if status == "acknowledged":
            timestamp_field = "acknowledged_at"
        elif status == "fixed":
            timestamp_field = "fixed_at"

        if timestamp_field:
            await self._db.execute(
                f"UPDATE findings SET status = ?, {timestamp_field} = ? WHERE id = ?",
                (status, datetime.now().isoformat(), finding_id),
            )
        else:
            await self._db.execute(
                "UPDATE findings SET status = ? WHERE id = ?",
                (status, finding_id),
            )

        await self._db.commit()
        return self._db.total_changes > 0

    async def delete_finding(self, finding_id: str) -> bool:
        """Delete a finding."""
        if not self._initialized:
            await self.initialize()

        await self._db.execute("DELETE FROM findings WHERE id = ?", (finding_id,))
        await self._db.commit()
        return self._db.total_changes > 0

    async def get_stats(self) -> dict:
        """
        Get statistics about findings.

        Returns:
            Dict with counts by loop, category, severity, status
        """
        if not self._initialized:
            await self.initialize()

        stats = {
            "total": 0,
            "by_loop": {},
            "by_category": {},
            "by_severity": {},
            "by_status": {},
        }

        # Total count
        async with self._db.execute("SELECT COUNT(*) as count FROM findings") as cursor:
            row = await cursor.fetchone()
            stats["total"] = row["count"]

        # By loop
        async with self._db.execute(
            "SELECT loop, COUNT(*) as count FROM findings GROUP BY loop"
        ) as cursor:
            async for row in cursor:
                stats["by_loop"][row["loop"]] = row["count"]

        # By category
        async with self._db.execute(
            "SELECT category, COUNT(*) as count FROM findings GROUP BY category"
        ) as cursor:
            async for row in cursor:
                stats["by_category"][row["category"]] = row["count"]

        # By severity
        async with self._db.execute(
            "SELECT severity, COUNT(*) as count FROM findings GROUP BY severity"
        ) as cursor:
            async for row in cursor:
                stats["by_severity"][row["severity"]] = row["count"]

        # By status
        async with self._db.execute(
            "SELECT status, COUNT(*) as count FROM findings GROUP BY status"
        ) as cursor:
            async for row in cursor:
                stats["by_status"][row["status"]] = row["count"]

        return stats

    async def add_scan_history(
        self,
        scan_type: str,
        loops_run: list[str],
        files_scanned: int,
        findings_count: int,
        duration_ms: int,
        started_at: datetime,
    ) -> int:
        """Record a scan in history."""
        if not self._initialized:
            await self.initialize()

        cursor = await self._db.execute(
            """
            INSERT INTO scan_history
            (scan_type, loops_run, files_scanned, findings_count, duration_ms, started_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scan_type,
                json.dumps(loops_run),
                files_scanned,
                findings_count,
                duration_ms,
                started_at.isoformat(),
            ),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def add_loop_history(
        self,
        loop_name: str,
        status: str,
        iterations: int,
        findings_count: int,
        duration_ms: int,
        error: Optional[str] = None,
    ) -> int:
        """Record a loop run in history."""
        if not self._initialized:
            await self.initialize()

        cursor = await self._db.execute(
            """
            INSERT INTO loop_history
            (loop_name, status, iterations, findings_count, duration_ms, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (loop_name, status, iterations, findings_count, duration_ms, error),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_recent_scans(self, limit: int = 10) -> list[dict]:
        """Get recent scan history."""
        if not self._initialized:
            await self.initialize()

        async with self._db.execute(
            "SELECT * FROM scan_history ORDER BY completed_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_loop_history(
        self, loop_name: Optional[str] = None, limit: int = 10
    ) -> list[dict]:
        """Get loop run history."""
        if not self._initialized:
            await self.initialize()

        if loop_name:
            query = "SELECT * FROM loop_history WHERE loop_name = ? ORDER BY completed_at DESC LIMIT ?"
            params = (loop_name, limit)
        else:
            query = "SELECT * FROM loop_history ORDER BY completed_at DESC LIMIT ?"
            params = (limit,)

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def clear_old_findings(self, days: int = 30) -> int:
        """
        Clear findings older than N days.

        Args:
            days: Age threshold in days

        Returns:
            Number of deleted findings
        """
        if not self._initialized:
            await self.initialize()

        await self._db.execute(
            "DELETE FROM findings WHERE detected_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        await self._db.commit()
        return self._db.total_changes

    async def vacuum(self):
        """Vacuum the database to reclaim space."""
        if not self._initialized:
            await self.initialize()

        await self._db.execute("VACUUM")
