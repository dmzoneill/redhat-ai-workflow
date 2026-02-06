"""
Slop Fixer Tools - Auto-fix high-confidence slop findings.

Provides MCP tools for:
- Listing fixable findings
- Applying fixes to high-confidence issues
- Dry-run mode to preview fixes

Usage:
    # List what can be fixed
    slop_fixable()

    # Preview fixes without applying
    slop_fix(dry_run=True)

    # Apply fixes
    slop_fix()
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.types import TextContent

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Add parent path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Import types directly to avoid triggering services.slop.__init__ which imports aiosqlite
# This prevents "threads can only be started once" errors when module is reloaded
import importlib.util  # noqa: E402

_types_path = Path(__file__).parent.parent.parent.parent / "services" / "slop" / "types.py"
_types_spec = importlib.util.spec_from_file_location("slop_types", _types_path)
_types_module = importlib.util.module_from_spec(_types_spec)
_types_spec.loader.exec_module(_types_module)

AUTO_FIXABLE_CATEGORIES = _types_module.AUTO_FIXABLE_CATEGORIES
SlopCategory = _types_module.SlopCategory
calculate_fix_confidence = _types_module.calculate_fix_confidence

logger = logging.getLogger(__name__)

# Database path
DEFAULT_DB_PATH = Path.home() / ".config" / "aa-workflow" / "slop.db"


def _get_db_connection():
    """Get async database connection context manager.

    Returns an aiosqlite connection that should be used with `async with`:
        async with _get_db_connection() as db:
            ...

    Note: Do NOT await this function - it returns a context manager directly.
    """
    import aiosqlite

    return aiosqlite.connect(str(DEFAULT_DB_PATH))


async def _get_fixable_findings(min_confidence: float = 0.90, limit: int = 50) -> list[dict]:
    """
    Get findings that meet auto-fix criteria.

    Args:
        min_confidence: Minimum confidence threshold
        limit: Maximum findings to return

    Returns:
        List of fixable findings with confidence scores
    """
    async with _get_db_connection() as db:
        db.row_factory = lambda cursor, row: dict(zip([col[0] for col in cursor.description], row))

        # Get open findings in auto-fixable categories
        categories = ", ".join(f"'{c.value}'" for c in AUTO_FIXABLE_CATEGORIES)
        query = f"""
            SELECT id, loop, file, line, category, severity, description, suggestion, tool
            FROM findings
            WHERE status = 'open'
            AND category IN ({categories})
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                    ELSE 5
                END,
                detected_at DESC
            LIMIT ?
        """

        cursor = await db.execute(query, (limit,))
        rows = await cursor.fetchall()

        # Calculate confidence for each finding
        fixable = []
        for row in rows:
            category = SlopCategory(row["category"]) if row["category"] in [c.value for c in SlopCategory] else None
            if category:
                confidence = calculate_fix_confidence(category, row.get("tool", ""))
                if confidence >= min_confidence:
                    row["confidence"] = confidence
                    fixable.append(row)

        return fixable


async def _apply_fix(finding: dict, dry_run: bool = False) -> dict:
    """
    Apply a fix for a single finding.

    Args:
        finding: The finding to fix
        dry_run: If True, just report what would be done

    Returns:
        Result dict with success status and details
    """
    # Import transforms module - use importlib to avoid relative import issues
    # when module is loaded dynamically by skill engine
    import importlib.util

    transforms_path = Path(__file__).parent / "transforms.py"
    transforms_spec = importlib.util.spec_from_file_location("transforms", transforms_path)
    transforms_module = importlib.util.module_from_spec(transforms_spec)
    transforms_spec.loader.exec_module(transforms_module)
    apply_transform = transforms_module.apply_transform

    file_path = finding["file"]
    category = finding["category"]
    line = finding["line"]
    suggestion = finding.get("suggestion", "")

    # Check file exists
    if not os.path.exists(file_path):
        return {
            "success": False,
            "finding_id": finding["id"],
            "error": f"File not found: {file_path}",
        }

    # Apply the appropriate transform
    result = await apply_transform(
        file_path=file_path,
        line=line,
        category=category,
        suggestion=suggestion,
        dry_run=dry_run,
    )

    return {
        "success": result.get("success", False),
        "finding_id": finding["id"],
        "file": file_path,
        "line": line,
        "category": category,
        "action": result.get("action", "unknown"),
        "diff": result.get("diff", ""),
        "error": result.get("error"),
    }


async def _mark_finding_fixed(finding_id: str, git_commit: str = None):
    """Mark a finding as fixed in the database."""
    async with _get_db_connection() as db:
        await db.execute(
            """
            UPDATE findings
            SET status = 'fixed', fixed_at = CURRENT_TIMESTAMP, git_commit = ?
            WHERE id = ?
            """,
            (git_commit, finding_id),
        )
        await db.commit()


async def _commit_fixes(files: list[str], message: str) -> str:
    """Commit fixed files to git."""
    if not files:
        return ""

    try:
        # Stage files
        subprocess.run(["git", "add"] + files, check=True, capture_output=True)

        # Commit
        subprocess.run(
            ["git", "commit", "-m", message],
            check=True,
            capture_output=True,
            text=True,
        )

        # Get commit hash
        hash_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return hash_result.stdout.strip()

    except subprocess.CalledProcessError as e:
        logger.error(f"Git commit failed: {e.stderr}")
        return ""


def register_tools(server: "FastMCP") -> int:
    """Register slop fixer tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """

    @server.tool()
    async def slop_fixable(
        min_confidence: float = 0.90,
        limit: int = 50,
    ) -> list[TextContent]:
        """
        List slop findings that can be auto-fixed.

        Shows findings that meet the confidence threshold for safe auto-fixing.
        Only includes categories that have deterministic fixes.

        Args:
            min_confidence: Minimum confidence score (0.0-1.0, default 0.90)
            limit: Maximum findings to return (default 50)

        Returns:
            List of fixable findings with confidence scores.
        """
        findings = await _get_fixable_findings(min_confidence, limit)

        if not findings:
            return [
                TextContent(
                    type="text",
                    text="No auto-fixable findings found.\n\n"
                    "Either the database is empty, or no findings meet the confidence threshold.\n"
                    "Run `slop_scan` first to detect issues.",
                )
            ]

        # Group by category
        by_category: dict[str, list[dict]] = {}
        for f in findings:
            cat = f["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(f)

        lines = [f"## Auto-Fixable Findings ({len(findings)} total)\n"]
        lines.append(f"Confidence threshold: {min_confidence:.0%}\n")

        for category, cat_findings in sorted(by_category.items()):
            lines.append(f"\n### {category} ({len(cat_findings)})\n")
            for f in cat_findings[:10]:  # Show max 10 per category
                conf = f.get("confidence", 0)
                tool = f.get("tool") or "LLM"
                lines.append(f"- `{f['file']}:{f['line']}` ({conf:.0%}, {tool})")
                lines.append(f"  {f['description'][:80]}...")
            if len(cat_findings) > 10:
                lines.append(f"  ... and {len(cat_findings) - 10} more")

        lines.append("\n---")
        lines.append("Run `slop_fix(dry_run=True)` to preview fixes.")
        lines.append("Run `slop_fix()` to apply fixes.")

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
    async def slop_fix(
        dry_run: bool = False,
        min_confidence: float = 0.90,
        limit: int = 20,
        commit: bool = True,
    ) -> list[TextContent]:
        """
        Auto-fix high-confidence slop findings.

        Applies safe, deterministic fixes to issues like:
        - unused_imports: Remove the import line
        - unused_variables: Remove or prefix with _
        - bare_except: Change to except Exception:
        - empty_except: Add logger.exception()

        Args:
            dry_run: If True, show what would be fixed without applying
            min_confidence: Minimum confidence score (default 0.90)
            limit: Maximum findings to fix per run (default 20)
            commit: If True, commit changes to git (default True)

        Returns:
            Summary of fixes applied (or would be applied in dry_run mode).
        """
        findings = await _get_fixable_findings(min_confidence, limit)

        if not findings:
            return [
                TextContent(
                    type="text",
                    text="No auto-fixable findings found.\n\n" "Run `slop_fixable()` to see what's available.",
                )
            ]

        mode = "DRY RUN - " if dry_run else ""
        lines = [f"## {mode}Slop Auto-Fix Results\n"]

        fixed_files = []
        fixed_ids = []
        errors = []

        for finding in findings:
            result = await _apply_fix(finding, dry_run=dry_run)

            if result["success"]:
                fixed_files.append(result["file"])
                fixed_ids.append(result["finding_id"])
                lines.append(f"✅ `{result['file']}:{result['line']}` - {result['action']}")
                if result.get("diff"):
                    lines.append(f"```diff\n{result['diff']}\n```")
            else:
                errors.append(result)
                lines.append(f"❌ `{finding['file']}:{finding['line']}` - {result.get('error', 'Unknown error')}")

        # Commit if not dry run
        commit_hash = ""
        if not dry_run and fixed_files and commit:
            unique_files = list(set(fixed_files))
            commit_msg = f"fix(slop): auto-fix {len(fixed_ids)} high-confidence issues\n\n"
            commit_msg += "Categories fixed:\n"
            categories = set(f["category"] for f in findings if f["id"] in fixed_ids)
            for cat in categories:
                count = sum(1 for f in findings if f["id"] in fixed_ids and f["category"] == cat)
                commit_msg += f"- {cat}: {count}\n"

            commit_hash = await _commit_fixes(unique_files, commit_msg)

            if commit_hash:
                # Mark findings as fixed in database
                for fid in fixed_ids:
                    await _mark_finding_fixed(fid, commit_hash)
                lines.append(f"\n**Committed:** `{commit_hash[:8]}`")
            else:
                lines.append("\n⚠️ Git commit failed - fixes applied but not committed")

        # Summary
        lines.append("\n---")
        lines.append(f"**Fixed:** {len(fixed_ids)}")
        lines.append(f"**Errors:** {len(errors)}")
        if dry_run:
            lines.append("\n*This was a dry run. Run `slop_fix()` to apply changes.*")

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
    async def slop_fix_stats() -> list[TextContent]:
        """
        Show statistics about slop findings and fixes.

        Returns:
            Statistics including total findings, fixable count, and fix history.
        """
        async with _get_db_connection() as db:
            db.row_factory = lambda cursor, row: dict(zip([col[0] for col in cursor.description], row))

            # Total by status
            cursor = await db.execute("SELECT status, COUNT(*) as count FROM findings GROUP BY status")
            status_counts = {row["status"]: row["count"] for row in await cursor.fetchall()}

            # By category
            cursor = await db.execute(
                """SELECT category, COUNT(*) as count FROM findings
                WHERE status = 'open' GROUP BY category ORDER BY count DESC"""
            )
            category_counts = await cursor.fetchall()

            # Recent fixes
            cursor = await db.execute(
                """
                SELECT category, COUNT(*) as count, MAX(fixed_at) as last_fixed
                FROM findings
                WHERE status = 'fixed'
                GROUP BY category
                ORDER BY last_fixed DESC
                LIMIT 10
                """
            )
            recent_fixes = await cursor.fetchall()

        lines = ["## Slop Findings Statistics\n"]

        # Status summary
        lines.append("### By Status")
        total = sum(status_counts.values())
        for status, count in sorted(status_counts.items()):
            lines.append(f"- **{status}**: {count}")
        lines.append(f"- **Total**: {total}\n")

        # Open by category
        if category_counts:
            lines.append("### Open by Category")
            for row in category_counts[:10]:
                cat = row["category"]
                count = row["count"]
                fixable = "✅" if cat in [c.value for c in AUTO_FIXABLE_CATEGORIES] else "❌"
                lines.append(f"- {cat}: {count} {fixable}")

        # Recent fixes
        if recent_fixes:
            lines.append("\n### Recently Fixed")
            for row in recent_fixes:
                lines.append(f"- {row['category']}: {row['count']} (last: {row['last_fixed']})")

        return [TextContent(type="text", text="\n".join(lines))]

    logger.info("Registered slop_fixer tools: slop_fixable, slop_fix, slop_fix_stats")
    return 3  # Number of tools registered
