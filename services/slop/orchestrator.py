"""
Slop Orchestrator - Manages Parallel Analysis Loops.

Coordinates multiple named analysis loops with:
- Semaphore limiting max concurrent loops (default: 3)
- Priority-based execution order
- Status tracking for UI display
- Start/stop control for individual loops

Usage:
    from services.slop.orchestrator import SlopOrchestrator

    orchestrator = SlopOrchestrator(max_parallel=3)
    await orchestrator.initialize()

    # Run all loops
    await orchestrator.run_all(parallel=True)

    # Run specific loops
    await orchestrator.run_specific(["leaky", "zombie"])

    # Get status
    status = orchestrator.get_status()
"""

import asyncio
import logging
from typing import Optional

from services.base.ai_router import get_ai_router
from services.slop.database import SlopDatabase
from services.slop.external_tools import ExternalTools
from services.slop.loops import LOOP_CONFIGS, PRIORITY_ORDER, AnalysisLoop, LoopResult

logger = logging.getLogger(__name__)


class SlopOrchestrator:
    """
    Manages named analysis loops with max N concurrent.

    Coordinates parallel execution while respecting resource limits.
    """

    def __init__(
        self,
        max_parallel: int = 3,
        db_path: Optional[str] = None,
        preferred_backend: Optional[str] = None,
        codebase_path: Optional[str] = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            max_parallel: Maximum concurrent loops (default: 3)
            db_path: Path to SQLite database
            preferred_backend: Preferred LLM backend
            codebase_path: Path to codebase to analyze
        """
        self.max_parallel = max_parallel
        self.codebase_path = codebase_path or "."

        self._semaphore = asyncio.Semaphore(max_parallel)
        self._db = SlopDatabase(db_path)
        self._ai_router = get_ai_router(preferred_backend)
        self._external_tools = ExternalTools()

        # Initialize loops
        self._loops: dict[str, AnalysisLoop] = {}
        self._loop_results: dict[str, LoopResult] = {}
        self._running = False
        self._initialized = False

    async def initialize(self):
        """Initialize the orchestrator and database."""
        if self._initialized:
            return

        # Initialize database
        await self._db.initialize()

        # Check AI router availability
        available = await self._ai_router.check_availability()
        available_backends = [k for k, v in available.items() if v]
        if not available_backends:
            logger.warning("No LLM backends available - analysis will fail")
        else:
            logger.info(f"Available LLM backends: {available_backends}")

        # Check external tools
        tools_available = await self._external_tools.check_availability()
        available_tools = [k for k, v in tools_available.items() if v]
        logger.info(f"Available external tools: {available_tools}")

        # Initialize all named loops
        for name, config in LOOP_CONFIGS.items():
            self._loops[name] = AnalysisLoop(
                name=name,
                config=config,
                db=self._db,
                ai_router=self._ai_router,
                external_tools=self._external_tools,
            )

        self._initialized = True
        logger.info(f"Orchestrator initialized with {len(self._loops)} loops, max {self.max_parallel} parallel")

    async def run_all(self, parallel: bool = True) -> dict[str, LoopResult]:
        """
        Run all loops in priority order.

        Args:
            parallel: If True, run max_parallel loops concurrently

        Returns:
            Dict mapping loop name to result
        """
        if not self._initialized:
            await self.initialize()

        self._running = True
        self._loop_results = {}

        logger.info(f"Starting all loops (parallel={parallel}, max={self.max_parallel})")

        try:
            if parallel:
                # Run with semaphore limiting concurrency
                tasks = []
                for name in PRIORITY_ORDER:
                    if name in self._loops:
                        task = asyncio.create_task(
                            self._run_with_semaphore(name),
                            name=f"loop-{name}",
                        )
                        tasks.append(task)

                # Wait for all to complete
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results
                for i, name in enumerate(PRIORITY_ORDER):
                    if name in self._loops:
                        result = results[i] if i < len(results) else None
                        if isinstance(result, Exception):
                            logger.error(f"Loop {name} raised exception: {result}")
                            self._loop_results[name] = LoopResult(
                                loop_name=name,
                                status="error",
                                iterations=0,
                                max_iterations=self._loops[name].max_iterations,
                                findings_count=0,
                                duration_ms=0,
                                error=str(result),
                            )
                        elif isinstance(result, LoopResult):
                            self._loop_results[name] = result
            else:
                # Sequential execution
                for name in PRIORITY_ORDER:
                    if name in self._loops:
                        result = await self._loops[name].run(codebase_path=self.codebase_path)
                        self._loop_results[name] = result

        finally:
            self._running = False

        # Log summary
        total_findings = sum(r.findings_count for r in self._loop_results.values())
        logger.info(f"All loops completed: {total_findings} total findings")

        return self._loop_results

    async def _run_with_semaphore(self, loop_name: str) -> LoopResult:
        """Run a single loop, respecting semaphore."""
        async with self._semaphore:
            logger.debug(f"Acquired semaphore for loop {loop_name}")
            result = await self._loops[loop_name].run(codebase_path=self.codebase_path)
            logger.debug(f"Released semaphore for loop {loop_name}")
            return result

    async def run_specific(self, loop_names: list[str], parallel: bool = True) -> dict[str, LoopResult]:
        """
        Run specific loops by name.

        Args:
            loop_names: List of loop names to run
            parallel: If True, run concurrently

        Returns:
            Dict mapping loop name to result
        """
        if not self._initialized:
            await self.initialize()

        # Validate loop names
        valid_names = [n for n in loop_names if n in self._loops]
        if not valid_names:
            logger.warning(f"No valid loop names in {loop_names}")
            return {}

        self._running = True
        results = {}

        logger.info(f"Starting loops: {valid_names}")

        try:
            if parallel:
                tasks = [asyncio.create_task(self._run_with_semaphore(name)) for name in valid_names]
                task_results = await asyncio.gather(*tasks, return_exceptions=True)

                for i, name in enumerate(valid_names):
                    result = task_results[i]
                    if isinstance(result, Exception):
                        results[name] = LoopResult(
                            loop_name=name,
                            status="error",
                            iterations=0,
                            max_iterations=self._loops[name].max_iterations,
                            findings_count=0,
                            duration_ms=0,
                            error=str(result),
                        )
                    else:
                        results[name] = result
            else:
                for name in valid_names:
                    results[name] = await self._loops[name].run(codebase_path=self.codebase_path)

        finally:
            self._running = False

        # Update stored results
        self._loop_results.update(results)

        return results

    async def stop_loop(self, loop_name: str) -> bool:
        """
        Stop a specific loop.

        Args:
            loop_name: Name of loop to stop

        Returns:
            True if stop was requested, False if loop not found
        """
        if loop_name not in self._loops:
            logger.warning(f"Unknown loop: {loop_name}")
            return False

        await self._loops[loop_name].stop()
        return True

    async def stop_all(self):
        """Stop all running loops."""
        logger.info("Stopping all loops")
        for loop in self._loops.values():
            await loop.stop()

    def get_status(self) -> dict:
        """
        Get status of all loops for UI display.

        Returns:
            Dict with loop statuses and summary
        """
        loops_status = {}
        for name, loop in self._loops.items():
            loops_status[name] = loop.get_status_dict()

        # Add results if available
        for name, result in self._loop_results.items():
            if name in loops_status:
                loops_status[name]["last_result"] = result.to_dict()

        return {
            "running": self._running,
            "max_parallel": self.max_parallel,
            "loops": loops_status,
            "priority_order": PRIORITY_ORDER,
        }

    def get_loop_status(self, loop_name: str) -> Optional[dict]:
        """Get status of a specific loop."""
        if loop_name not in self._loops:
            return None
        return self._loops[loop_name].get_status_dict()

    async def get_findings(
        self,
        loop_name: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get findings from database.

        Args:
            loop_name: Filter by loop name
            severity: Filter by severity
            status: Filter by status
            limit: Maximum results

        Returns:
            List of finding dicts
        """
        filters = {}
        if loop_name:
            filters["loop"] = loop_name
        if severity:
            filters["severity"] = severity
        if status:
            filters["status"] = status

        return await self._db.get_findings(filters=filters, limit=limit)

    async def get_stats(self) -> dict:
        """Get statistics from database."""
        return await self._db.get_stats()

    async def acknowledge_finding(self, finding_id: str) -> bool:
        """Mark a finding as acknowledged."""
        return await self._db.update_status(finding_id, "acknowledged")

    async def mark_false_positive(self, finding_id: str) -> bool:
        """Mark a finding as false positive."""
        return await self._db.update_status(finding_id, "false_positive")

    async def mark_fixed(self, finding_id: str) -> bool:
        """Mark a finding as fixed."""
        return await self._db.update_status(finding_id, "fixed")

    @property
    def is_running(self) -> bool:
        """Whether any loops are currently running."""
        return self._running

    @property
    def database(self) -> SlopDatabase:
        """Get the database instance."""
        return self._db
