"""Poll Engine - Event-based triggers via polling GitLab/Jira.

Provides:
- PollEngine: Periodically checks external sources for conditions
- Deduplication to avoid repeated triggers
- Integration with scheduler for triggering skills
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Project paths
PROJECT_DIR = Path(__file__).parent.parent.parent.parent


def parse_duration(duration_str: str) -> timedelta:
    """Parse a duration string like '1h', '30m', '2d' into timedelta.

    Supported formats:
    - Xs or Xsec or Xseconds: seconds
    - Xm or Xmin or Xminutes: minutes
    - Xh or Xhr or Xhours: hours
    - Xd or Xday or Xdays: days
    - Xw or Xweek or Xweeks: weeks
    """
    duration_str = duration_str.strip().lower()

    # Match number and unit
    match = re.match(r"^(\d+)\s*([a-z]+)$", duration_str)
    if not match:
        raise ValueError(f"Invalid duration format: {duration_str}")

    value = int(match.group(1))
    unit = match.group(2)

    if unit in ("s", "sec", "second", "seconds"):
        return timedelta(seconds=value)
    elif unit in ("m", "min", "minute", "minutes"):
        return timedelta(minutes=value)
    elif unit in ("h", "hr", "hour", "hours"):
        return timedelta(hours=value)
    elif unit in ("d", "day", "days"):
        return timedelta(days=value)
    elif unit in ("w", "week", "weeks"):
        return timedelta(weeks=value)
    else:
        raise ValueError(f"Unknown duration unit: {unit}")


class PollCondition:
    """Evaluates conditions on polled data."""

    def __init__(self, condition_str: str):
        """Initialize with a condition string like 'age > 3d' or 'count > 0'."""
        self.condition_str = condition_str
        self._parse_condition()

    def _parse_condition(self):
        """Parse the condition string."""
        # Supported formats:
        # - age > 3d (item age greater than 3 days)
        # - count > 0 (number of items greater than 0)
        # - any (always true if any results)

        self.condition_type = "any"
        self.operator = ">"
        self.threshold = 0
        self.threshold_duration: timedelta | None = None

        if not self.condition_str or self.condition_str.lower() == "any":
            return

        # Parse age condition
        age_match = re.match(
            r"age\s*([<>=!]+)\s*(\d+[a-z]+)", self.condition_str, re.IGNORECASE
        )
        if age_match:
            self.condition_type = "age"
            self.operator = age_match.group(1)
            self.threshold_duration = parse_duration(age_match.group(2))
            return

        # Parse count condition
        count_match = re.match(
            r"count\s*([<>=!]+)\s*(\d+)", self.condition_str, re.IGNORECASE
        )
        if count_match:
            self.condition_type = "count"
            self.operator = count_match.group(1)
            self.threshold = int(count_match.group(2))
            return

    def evaluate(self, items: list[dict]) -> tuple[bool, list[dict]]:
        """Evaluate condition against items.

        Returns:
            Tuple of (condition_met, matching_items)
        """
        if self.condition_type == "any":
            return len(items) > 0, items

        if self.condition_type == "count":
            count = len(items)
            met = self._compare(count, self.threshold)
            return met, items if met else []

        if self.condition_type == "age":
            now = datetime.now()
            matching = []

            for item in items:
                # Try to get created/updated date from item
                date_str = (
                    item.get("created_at") or item.get("updated_at") or item.get("date")
                )
                if not date_str:
                    continue

                try:
                    # Parse ISO date
                    if isinstance(date_str, str):
                        # Handle various ISO formats
                        date_str = date_str.replace("Z", "+00:00")
                        if "+" in date_str:
                            item_date = datetime.fromisoformat(date_str.split("+")[0])
                        else:
                            item_date = datetime.fromisoformat(date_str)
                    else:
                        item_date = date_str

                    age = now - item_date

                    if self.threshold_duration and self._compare_duration(
                        age, self.threshold_duration
                    ):
                        matching.append(item)

                except Exception as e:
                    logger.debug(f"Failed to parse date {date_str}: {e}")

            return len(matching) > 0, matching

        return False, []

    def _compare(self, value: int, threshold: int) -> bool:
        """Compare value against threshold using operator."""
        if self.operator == ">":
            return value > threshold
        elif self.operator == ">=":
            return value >= threshold
        elif self.operator == "<":
            return value < threshold
        elif self.operator == "<=":
            return value <= threshold
        elif self.operator in ("==", "="):
            return value == threshold
        elif self.operator in ("!=", "<>"):
            return value != threshold
        return False

    def _compare_duration(self, value: timedelta, threshold: timedelta) -> bool:
        """Compare duration against threshold using operator."""
        if self.operator == ">":
            return value > threshold
        elif self.operator == ">=":
            return value >= threshold
        elif self.operator == "<":
            return value < threshold
        elif self.operator == "<=":
            return value <= threshold
        return False


class PollSource:
    """A source to poll for data."""

    def __init__(
        self,
        name: str,
        source_type: str,
        args: dict,
        condition: str,
        server: "FastMCP | None" = None,
    ):
        self.name = name
        self.source_type = source_type
        self.args = args
        self.condition = PollCondition(condition)
        self.server = server
        self.last_poll: datetime | None = None
        self.last_result: list[dict] = []

    async def poll(self) -> tuple[bool, list[dict]]:
        """Poll the source and evaluate condition.

        Returns:
            Tuple of (condition_met, matching_items)
        """
        self.last_poll = datetime.now()

        try:
            items = await self._fetch_data()
            self.last_result = items
            return self.condition.evaluate(items)
        except Exception as e:
            logger.error(f"Poll source {self.name} failed: {e}")
            return False, []

    async def _fetch_data(self) -> list[dict]:
        """Fetch data from the source."""
        if self.source_type == "gitlab_mr_list":
            return await self._fetch_gitlab_mrs()
        elif self.source_type == "jira_search":
            return await self._fetch_jira_issues()
        else:
            logger.warning(f"Unknown poll source type: {self.source_type}")
            return []

    async def _fetch_gitlab_mrs(self) -> list[dict]:
        """Fetch GitLab merge requests."""
        if not self.server:
            return []

        try:
            # Call the gitlab_mr_list tool
            result = await self.server.call_tool("gitlab_mr_list", self.args)

            # Parse the result
            if isinstance(result, list) and result:
                text = result[0].text if hasattr(result[0], "text") else str(result[0])
                return self._parse_mr_list(text)

            return []
        except Exception as e:
            logger.error(f"Failed to fetch GitLab MRs: {e}")
            return []

    def _parse_mr_list(self, text: str) -> list[dict]:
        """Parse MR list output into structured data."""
        items = []

        # Parse lines like: !123 - Title (author) - created_at
        for line in text.split("\n"):
            if not line.strip() or line.startswith("#"):
                continue

            # Try to extract MR info
            mr_match = re.search(r"!(\d+)", line)
            if mr_match:
                mr_id = mr_match.group(1)

                # Try to extract date
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})", line)
                created_at = date_match.group(1) if date_match else None

                items.append(
                    {
                        "id": mr_id,
                        "title": line,
                        "created_at": created_at,
                    }
                )

        return items

    async def _fetch_jira_issues(self) -> list[dict]:
        """Fetch Jira issues."""
        if not self.server:
            return []

        try:
            # Call the jira_search tool
            result = await self.server.call_tool("jira_search", self.args)

            # Parse the result
            if isinstance(result, list) and result:
                text = result[0].text if hasattr(result[0], "text") else str(result[0])
                return self._parse_jira_list(text)

            return []
        except Exception as e:
            logger.error(f"Failed to fetch Jira issues: {e}")
            return []

    def _parse_jira_list(self, text: str) -> list[dict]:
        """Parse Jira list output into structured data."""
        items = []

        # Parse lines with issue keys like AAP-12345
        for line in text.split("\n"):
            if not line.strip():
                continue

            key_match = re.search(r"([A-Z]+-\d+)", line)
            if key_match:
                items.append(
                    {
                        "key": key_match.group(1),
                        "title": line,
                    }
                )

        return items


class PollEngine:
    """Engine for polling external sources and triggering skills."""

    def __init__(
        self,
        server: "FastMCP | None" = None,
        job_callback: Callable | None = None,
    ):
        """Initialize the poll engine.

        Args:
            server: FastMCP server for tool calls
            job_callback: Async callback to trigger jobs when conditions are met
        """
        self.server = server
        self.job_callback = job_callback
        self.sources: dict[str, PollSource] = {}
        self.jobs: list[dict] = []
        self._running = False
        self._task: asyncio.Task | None = None

        # Deduplication: track triggered items to avoid re-triggering
        self._triggered_hashes: dict[str, datetime] = {}
        self._dedup_ttl = timedelta(hours=24)  # Don't re-trigger same item for 24h
        self._max_triggered_hashes = 1000  # Prevent unbounded memory growth

    def configure(self, poll_sources: dict, poll_jobs: list[dict]):
        """Configure poll sources and jobs.

        Args:
            poll_sources: Dict of source name -> source config
            poll_jobs: List of poll job configs
        """
        # Create poll sources
        self.sources = {}
        for name, config in poll_sources.items():
            self.sources[name] = PollSource(
                name=name,
                source_type=config.get("type", ""),
                args=config.get("args", {}),
                condition=config.get("condition", "any"),
                server=self.server,
            )

        self.jobs = poll_jobs

    async def start(self):
        """Start the poll engine."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"Poll engine started with {len(self.jobs)} jobs")

    async def stop(self):
        """Stop the poll engine."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Poll engine stopped")

    async def _poll_loop(self):
        """Main polling loop."""
        # Track next poll time for each job
        next_poll: dict[str, datetime] = {}

        while self._running:
            now = datetime.now()

            for job in self.jobs:
                job_name = job.get("name", "unnamed")
                interval_str = job.get("poll_interval", "1h")
                condition_name = job.get("condition", "")

                # Initialize next poll time
                if job_name not in next_poll:
                    next_poll[job_name] = now

                # Check if it's time to poll
                if now < next_poll[job_name]:
                    continue

                # Update next poll time
                try:
                    interval = parse_duration(interval_str)
                    next_poll[job_name] = now + interval
                except ValueError as e:
                    logger.error(f"Invalid poll interval for {job_name}: {e}")
                    next_poll[job_name] = now + timedelta(hours=1)
                    continue

                # Get the source
                source = self.sources.get(condition_name)
                if not source:
                    logger.warning(f"Poll source not found: {condition_name}")
                    continue

                # Poll the source
                logger.debug(f"Polling {condition_name} for job {job_name}")
                condition_met, items = await source.poll()

                if condition_met:
                    # Filter out already-triggered items
                    new_items = self._filter_triggered(job_name, items)

                    if new_items:
                        logger.info(
                            f"Poll condition met for {job_name}: {len(new_items)} new items"
                        )
                        await self._trigger_job(job, new_items)

            # Sleep before next iteration
            await asyncio.sleep(60)  # Check every minute

    def _filter_triggered(self, job_name: str, items: list[dict]) -> list[dict]:
        """Filter out items that have already been triggered recently."""
        now = datetime.now()
        new_items = []

        # Clean up old entries
        self._triggered_hashes = {
            k: v for k, v in self._triggered_hashes.items() if now - v < self._dedup_ttl
        }

        # Also enforce max size by removing oldest entries if over limit
        if len(self._triggered_hashes) > self._max_triggered_hashes:
            # Sort by timestamp and keep only the newest entries
            sorted_hashes = sorted(
                self._triggered_hashes.items(), key=lambda x: x[1], reverse=True
            )
            self._triggered_hashes = dict(sorted_hashes[: self._max_triggered_hashes])

        for item in items:
            # Create hash of item for deduplication
            item_hash = self._hash_item(job_name, item)

            if item_hash not in self._triggered_hashes:
                new_items.append(item)
                self._triggered_hashes[item_hash] = now

        return new_items

    def _hash_item(self, job_name: str, item: dict) -> str:
        """Create a hash for deduplication."""
        # Use job name + item ID/key for uniqueness
        item_id = item.get("id") or item.get("key") or str(item)
        content = f"{job_name}:{item_id}"
        return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()

    async def _trigger_job(self, job: dict, items: list[dict]):
        """Trigger a job with the matching items."""
        if not self.job_callback:
            logger.warning("No job callback configured")
            return

        job_name = job.get("name", "unnamed")
        skill = job.get("skill", "")
        inputs = job.get("inputs", {}).copy()
        notify = job.get("notify", [])

        # Add triggered items to inputs
        inputs["_triggered_items"] = items
        inputs["_triggered_count"] = len(items)

        try:
            await self.job_callback(
                job_name=job_name,
                skill=skill,
                inputs=inputs,
                notify=notify,
            )
        except Exception as e:
            logger.error(f"Failed to trigger job {job_name}: {e}")

    async def poll_now(self, source_name: str) -> dict:
        """Manually poll a source immediately.

        Args:
            source_name: Name of the source to poll

        Returns:
            Dict with poll results
        """
        source = self.sources.get(source_name)
        if not source:
            return {"success": False, "error": f"Source not found: {source_name}"}

        condition_met, items = await source.poll()

        return {
            "success": True,
            "source": source_name,
            "condition_met": condition_met,
            "items_count": len(items),
            "items": items[:10],  # Limit to 10 items in response
        }

    def get_status(self) -> dict:
        """Get poll engine status."""
        return {
            "running": self._running,
            "sources": list(self.sources.keys()),
            "jobs": len(self.jobs),
            "triggered_items_cached": len(self._triggered_hashes),
        }


# Global poll engine instance
_poll_engine: PollEngine | None = None


def get_poll_engine() -> PollEngine | None:
    """Get the global poll engine instance."""
    return _poll_engine


def init_poll_engine(
    server: "FastMCP | None" = None,
    job_callback: Callable | None = None,
) -> PollEngine:
    """Initialize the global poll engine instance."""
    global _poll_engine
    _poll_engine = PollEngine(server=server, job_callback=job_callback)
    return _poll_engine
