"""
Slop Bot Daemon - Orchestrator-based Code Quality Monitor.

A systemd service with named parallel analysis loops that each focus on
one code smell at a time, iterating until done before moving to the next task.

Features:
- File watcher triggers analysis on code changes
- Max 3 concurrent analysis loops (configurable)
- SQLite database for findings
- D-Bus interface for control and status
- VSCode integration via D-Bus

Usage:
    # Run directly
    python -m services.slop --dbus

    # Via systemd
    systemctl --user start bot-slop

    # Check status
    python -m services.slop --status
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase
from services.base.sleep_wake import SleepWakeAwareDaemon
from services.slop.orchestrator import SlopOrchestrator

logger = logging.getLogger(__name__)


class SlopDaemon(SleepWakeAwareDaemon, DaemonDBusBase, BaseDaemon):
    """
    Orchestrator-based code quality daemon with named loops.

    Monitors code for quality issues using parallel analysis loops,
    each focused on one type of code smell.
    """

    name = "slop"
    description = "Slop Bot - Code Quality Monitor"

    # D-Bus configuration
    service_name = "com.aiworkflow.BotSlop"
    object_path = "/com/aiworkflow/BotSlop"
    interface_name = "com.aiworkflow.BotSlop"

    def __init__(
        self,
        verbose: bool = False,
        enable_dbus: bool = False,
        max_parallel: int = 3,
        codebase_path: Optional[str] = None,
        db_path: Optional[str] = None,
        preferred_backend: Optional[str] = None,
    ):
        """
        Initialize the Slop Bot daemon.

        Args:
            verbose: Enable verbose logging
            enable_dbus: Enable D-Bus interface
            max_parallel: Maximum concurrent analysis loops
            codebase_path: Path to codebase to analyze
            db_path: Path to SQLite database
            preferred_backend: Preferred LLM backend
        """
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)
        SleepWakeAwareDaemon.__init__(self)

        self._max_parallel = max_parallel
        self._codebase_path = codebase_path or str(Path.cwd())
        self._db_path = db_path
        self._preferred_backend = preferred_backend

        self._orchestrator: Optional[SlopOrchestrator] = None
        self._scan_in_progress = False
        self._last_scan_time: Optional[datetime] = None
        self._scan_count = 0

        # Register D-Bus handlers
        self.register_handler("scan_now", self._handle_scan_now)
        self.register_handler("scan_loops", self._handle_scan_loops)
        self.register_handler("stop_loop", self._handle_stop_loop)
        self.register_handler("stop_all", self._handle_stop_all)
        self.register_handler("get_loop_status", self._handle_get_loop_status)
        self.register_handler("get_findings", self._handle_get_findings)
        self.register_handler("get_findings_by_loop", self._handle_get_findings_by_loop)
        self.register_handler("acknowledge", self._handle_acknowledge)
        self.register_handler("mark_false_positive", self._handle_mark_false_positive)
        self.register_handler("mark_fixed", self._handle_mark_fixed)
        self.register_handler("get_stats", self._handle_get_stats)

    async def get_service_stats(self) -> dict:
        """Return service-specific statistics."""
        stats = {
            "scan_in_progress": self._scan_in_progress,
            "scan_count": self._scan_count,
            "last_scan_time": (
                self._last_scan_time.isoformat() if self._last_scan_time else None
            ),
            "max_parallel": self._max_parallel,
            "codebase_path": self._codebase_path,
        }

        if self._orchestrator:
            stats["orchestrator"] = self._orchestrator.get_status()
            db_stats = await self._orchestrator.get_stats()
            stats["findings"] = db_stats

        return stats

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        status = {
            "scan_in_progress": self._scan_in_progress,
            "scan_count": self._scan_count,
            "last_scan_time": (
                self._last_scan_time.isoformat() if self._last_scan_time else None
            ),
        }

        if self._orchestrator:
            status["loops"] = self._orchestrator.get_status()

        return status

    async def health_check(self) -> dict:
        """Perform a health check on the service."""
        self._last_health_check = time.time()

        checks = {
            "running": self.is_running,
            "orchestrator_initialized": self._orchestrator is not None,
        }

        # Check if we can access the database
        if self._orchestrator:
            try:
                await self._orchestrator.get_stats()
                checks["database_accessible"] = True
            except Exception:
                checks["database_accessible"] = False
        else:
            checks["database_accessible"] = False

        healthy = all(checks.values())

        return {
            "healthy": healthy,
            "checks": checks,
            "message": "Service is healthy" if healthy else "Service has issues",
            "timestamp": self._last_health_check,
        }

    async def on_system_wake(self):
        """
        Called when system wakes from sleep.

        Triggers a fresh analysis scan to catch any changes made while asleep.
        """
        logger.info("System wake detected - triggering analysis scan")
        if self._orchestrator and not self._scan_in_progress:
            asyncio.create_task(self._run_analysis())

    async def run_daemon(self):
        """Main daemon loop - stays alive and responds to D-Bus scan requests."""
        self.start_time = time.time()
        self.is_running = True

        logger.info(f"Starting Slop Bot daemon (max_parallel={self._max_parallel})")
        logger.info(f"Codebase path: {self._codebase_path}")

        # Initialize orchestrator
        self._orchestrator = SlopOrchestrator(
            max_parallel=self._max_parallel,
            db_path=self._db_path,
            preferred_backend=self._preferred_backend,
            codebase_path=self._codebase_path,
        )
        await self._orchestrator.initialize()

        # Start D-Bus if enabled (for status queries and scan_now)
        if self.enable_dbus:
            await self.start_dbus()
            logger.info("D-Bus interface started - waiting for scan_now requests")

        # Run initial analysis on startup
        logger.info("Running initial analysis...")
        await self._run_analysis()

        # Stay alive and wait for D-Bus requests (scan_now, etc.)
        # The daemon responds to:
        # - scan_now: Trigger a new scan
        # - scan_loops: Run specific loops
        # - get_findings: Query findings
        # - acknowledge/mark_fixed/mark_false_positive: Update status
        logger.info("Daemon ready - waiting for D-Bus commands")
        while not self._shutdown_event.is_set():
            # Wait for shutdown signal, checking every 60 seconds
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                # Just a heartbeat - daemon is still alive
                logger.debug(f"Daemon alive - {self._scan_count} scans completed")
                continue

        # Cleanup on shutdown
        logger.info("Shutdown requested, cleaning up...")
        if self._orchestrator:
            await self._orchestrator.stop_all()
            # Close the database connection to prevent file descriptor leak
            if self._orchestrator.database:
                await self._orchestrator.database.close()

        self.is_running = False
        logger.info("Slop Bot daemon stopped")

    async def _run_analysis(self):
        """Run full analysis with all loops."""
        if self._scan_in_progress:
            logger.warning("Scan already in progress, skipping")
            return

        self._scan_in_progress = True
        self._last_scan_time = datetime.now()
        self._scan_count += 1

        logger.info(f"Starting analysis #{self._scan_count}")
        self.emit_status_changed("scanning")

        try:
            results = await self._orchestrator.run_all(parallel=True)

            total_findings = sum(r.findings_count for r in results.values())
            logger.info(f"Analysis complete: {total_findings} findings")

            self.emit_event(
                "scan_complete",
                json.dumps(
                    {
                        "scan_count": self._scan_count,
                        "total_findings": total_findings,
                        "loops_run": list(results.keys()),
                    }
                ),
            )

        except Exception as e:
            logger.exception(f"Analysis error: {e}")
            self.emit_event("scan_error", json.dumps({"error": str(e)}))

        finally:
            self._scan_in_progress = False
            self.emit_status_changed("idle")

    # ==================== D-Bus Handlers ====================

    async def _handle_scan_now(self) -> dict:
        """Trigger immediate full scan of all loops."""
        if self._scan_in_progress:
            return {
                "status": "already_running",
                "loop_status": (
                    self._orchestrator.get_status() if self._orchestrator else {}
                ),
            }

        asyncio.create_task(self._run_analysis())
        return {
            "status": "started",
            "loop_status": (
                self._orchestrator.get_status() if self._orchestrator else {}
            ),
        }

    async def _handle_scan_loops(self, loops: list = None) -> dict:
        """Run specific loops by name."""
        if not loops:
            return {"error": "No loops specified"}

        if not self._orchestrator:
            return {"error": "Orchestrator not initialized"}

        results = await self._orchestrator.run_specific(loops)
        return {
            "status": "completed",
            "results": {name: result.to_dict() for name, result in results.items()},
        }

    async def _handle_stop_loop(self, loop_name: str = None) -> dict:
        """Stop a specific loop."""
        if not loop_name:
            return {"error": "No loop name specified"}

        if not self._orchestrator:
            return {"error": "Orchestrator not initialized"}

        success = await self._orchestrator.stop_loop(loop_name)
        return {"success": success, "loop": loop_name}

    async def _handle_stop_all(self) -> dict:
        """Stop all running loops."""
        if not self._orchestrator:
            return {"error": "Orchestrator not initialized"}

        await self._orchestrator.stop_all()
        return {"success": True}

    async def _handle_get_loop_status(self) -> dict:
        """Get status of all named loops."""
        if not self._orchestrator:
            return {"error": "Orchestrator not initialized"}

        # Get orchestrator status and merge with daemon-level stats
        status = self._orchestrator.get_status()
        status["scan_in_progress"] = self._scan_in_progress
        status["scan_count"] = self._scan_count
        status["last_scan_time"] = (
            self._last_scan_time.isoformat() if self._last_scan_time else None
        )
        return status

    async def _handle_get_findings(
        self,
        loop: str = None,
        severity: str = None,
        status: str = None,
        limit: int = 100,
    ) -> dict:
        """Get findings with optional filters."""
        if not self._orchestrator:
            return {"error": "Orchestrator not initialized"}

        findings = await self._orchestrator.get_findings(
            loop_name=loop,
            severity=severity,
            status=status,
            limit=limit,
        )
        return {"findings": findings, "count": len(findings)}

    async def _handle_get_findings_by_loop(self, loop_name: str = None) -> dict:
        """Get all findings from a specific loop."""
        if not loop_name:
            return {"error": "No loop name specified"}

        return await self._handle_get_findings(loop=loop_name)

    async def _handle_acknowledge(self, finding_id: str = None) -> dict:
        """Mark a finding as acknowledged."""
        if not finding_id:
            return {"error": "No finding ID specified"}

        if not self._orchestrator:
            return {"error": "Orchestrator not initialized"}

        success = await self._orchestrator.acknowledge_finding(finding_id)
        return {"success": success, "finding_id": finding_id}

    async def _handle_mark_false_positive(self, finding_id: str = None) -> dict:
        """Mark a finding as false positive."""
        if not finding_id:
            return {"error": "No finding ID specified"}

        if not self._orchestrator:
            return {"error": "Orchestrator not initialized"}

        success = await self._orchestrator.mark_false_positive(finding_id)
        return {"success": success, "finding_id": finding_id}

    async def _handle_mark_fixed(self, finding_id: str = None) -> dict:
        """Mark a finding as fixed."""
        if not finding_id:
            return {"error": "No finding ID specified"}

        if not self._orchestrator:
            return {"error": "Orchestrator not initialized"}

        success = await self._orchestrator.mark_fixed(finding_id)
        return {"success": success, "finding_id": finding_id}

    async def _handle_get_stats(self) -> dict:
        """Get statistics from database."""
        if not self._orchestrator:
            return {"error": "Orchestrator not initialized"}

        return await self._orchestrator.get_stats()

    @classmethod
    def create_argument_parser(cls):
        """Create argument parser with slop-specific options."""
        parser = super().create_argument_parser()

        parser.add_argument(
            "--max-parallel",
            type=int,
            default=3,
            help="Maximum concurrent analysis loops (default: 3)",
        )
        parser.add_argument(
            "--codebase",
            type=str,
            default=None,
            help="Path to codebase to analyze (default: current directory)",
        )
        parser.add_argument(
            "--db-path",
            type=str,
            default=None,
            help="Path to SQLite database",
        )
        parser.add_argument(
            "--backend",
            type=str,
            default=None,
            choices=["claude", "gemini", "codex", "opencode"],
            help="Preferred LLM backend",
        )

        return parser

    @classmethod
    def main(cls, args=None):
        """Main entry point with custom argument handling."""
        parser = cls.create_argument_parser()
        parsed = parser.parse_args(args)

        # Handle --status
        if parsed.status:
            import sys

            sys.exit(cls.handle_status())

        # Handle --stop
        if parsed.stop:
            import sys

            sys.exit(cls.handle_stop())

        # Configure logging
        cls.configure_logging(verbose=parsed.verbose)

        # Create and run daemon with custom options
        daemon = cls(
            verbose=parsed.verbose,
            enable_dbus=parsed.enable_dbus,
            max_parallel=parsed.max_parallel,
            codebase_path=parsed.codebase,
            db_path=parsed.db_path,
            preferred_backend=parsed.backend,
        )
        daemon.run()


if __name__ == "__main__":
    SlopDaemon.main()
