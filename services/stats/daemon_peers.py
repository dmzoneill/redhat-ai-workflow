"""Peer collection and comparison mixin for StatsDaemon."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime
from pathlib import Path

from server.paths import AA_CONFIG_DIR, get_performance_summary_path
from services.stats.peer_backfill import (
    build_filter_label,
    compute_peer_benchmarks,
    get_weekdays_in_quarter_range,
)
from services.stats.performance_scoring import (
    compute_competency_percentages,
    compute_daily_points,
    dedup_events_by_jira_key,
    is_primary_only_event,
    normalize_strategy_bonus,
)
from services.stats.scorer import (
    DEFAULT_GLOBALS,
    get_effective_defs,
    get_level_weights,
    get_merged_config,
    get_peer_comparable_config,
    get_source_daily_caps,
    get_strategy_alignment_config,
)
from services.stats.strategy import build_strategy_context_index

MAX_PEER_BACKFILL_ERRORS = 50

logger = logging.getLogger(__name__)


class PeerCollectorMixin:
    """Mixin providing peer collection, backfill, and benchmark methods."""

    def _load_peers_config(self) -> dict[str, list[dict]]:
        """Load peers roster from org_roster.json (preferred) or config.json."""
        org_roster = AA_CONFIG_DIR / "performance" / "org" / "org_roster.json"
        try:
            if org_roster.exists():
                with open(org_roster, encoding="utf-8") as f:
                    roster = json.load(f)
                peers = roster.get("peers", {})
                if peers:
                    logger.info(
                        "Loaded %d peer levels from org_roster.json",
                        len(peers),
                    )
                    return peers
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load org_roster.json: %s", e)

        config_paths = [
            Path(__file__).parent.parent.parent / "config.json",
            AA_CONFIG_DIR / "config.json",
        ]
        for cfg_path in config_paths:
            try:
                if cfg_path.exists():
                    with open(cfg_path, encoding="utf-8") as f:
                        config = json.load(f)
                    peers = config.get("peers", {})
                    if peers:
                        return peers
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read config file: %s", e)
                continue
        return {}

    def _update_peer_summary(
        self,
        username: str,
        level: str,
        year: int | None = None,
        quarter: int | None = None,
    ) -> dict:
        """Build summary.json for a single peer from their daily files.

        Computes both raw cumulative scores and peer-comparable scores
        (strategy bonus stripped) so benchmarks can be built from either.
        """
        perf_dir = self._get_perf_dir(year, quarter)
        peer_daily_dir = perf_dir / "peers" / username / "daily"
        if not peer_daily_dir.exists():
            return {}

        _, _, daily_cap, target_per_competency = get_effective_defs()

        cumulative_points: dict[str, int] = {}
        comparable_points: dict[str, int] = {}
        total_events = 0
        days_with_events = 0
        event_counts: dict[str, int] = {}

        for daily_file in sorted(peer_daily_dir.glob("*.json")):
            try:
                with open(daily_file, encoding="utf-8") as f:
                    data = json.load(f)
                for comp_id, pts in data.get("daily_points", {}).items():
                    cumulative_points[comp_id] = cumulative_points.get(comp_id, 0) + pts
                day_events = data.get("events", [])
                total_events += len(day_events)
                if day_events:
                    days_with_events += 1

                pc_daily: dict[str, int] = {}
                for ev in day_events:
                    src = ev.get("source", "unknown")
                    event_counts[src] = event_counts.get(src, 0) + 1

                    if not is_primary_only_event(ev, get_peer_comparable_config()):
                        ev_pts = normalize_strategy_bonus(
                            ev.get("points", {}),
                            ev,
                            bonus_multiplier=get_strategy_alignment_config().get(
                                "bonus_multiplier", 1.5
                            ),
                        )
                        for comp_id, pts in ev_pts.items():
                            current = pc_daily.get(comp_id, 0)
                            pc_daily[comp_id] = min(current + pts, daily_cap)

                for comp_id, pts in pc_daily.items():
                    comparable_points[comp_id] = comparable_points.get(comp_id, 0) + pts
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read peer daily file: %s", e)
                continue

        lw = get_level_weights(level)
        target_scale = lw.get("target_scale", 1.0)
        effective_target = max(round(target_per_competency * target_scale), 1)

        cumulative_pct = compute_competency_percentages(
            cumulative_points, effective_target
        )
        overall = round(sum(cumulative_pct.values()) / max(len(cumulative_pct), 1))

        comparable_pct = compute_competency_percentages(
            comparable_points, effective_target
        )
        comparable_overall = round(
            sum(comparable_pct.values()) / max(len(comparable_pct), 1)
        )

        now = datetime.now()
        y = year or now.year
        q = quarter or ((now.month - 1) // 3 + 1)

        days_captured = len(list(peer_daily_dir.glob("*.json")))
        avg_daily_events = round(total_events / max(days_captured, 1), 1)

        summary = {
            "username": username,
            "level": level,
            "year": y,
            "quarter": q,
            "cumulative_points": cumulative_points,
            "cumulative_percentage": cumulative_pct,
            "overall_percentage": overall,
            "comparable_points": comparable_points,
            "comparable_percentage": comparable_pct,
            "comparable_overall": comparable_overall,
            "total_events": total_events,
            "days_captured": days_captured,
            "days_with_events": days_with_events,
            "avg_daily_events": avg_daily_events,
            "event_counts_by_source": event_counts,
            "effective_target": effective_target,
            "last_updated": now.isoformat(),
        }

        peer_dir = perf_dir / "peers" / username
        peer_dir.mkdir(parents=True, exist_ok=True)
        with open(peer_dir / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        return summary

    @staticmethod
    def _compute_distribution(values: list[float | int]) -> dict:
        """Compute min/max/median/p25/p75/avg from a list of numeric values."""
        from services.stats.peer_backfill import compute_distribution

        return compute_distribution(values)

    def _update_peer_benchmarks(
        self,
        year: int | None = None,
        quarter: int | None = None,
    ) -> dict:
        """Aggregate all peer summaries into benchmarks.json grouped by level.

        Produces both raw and comparable (strategy-normalized) benchmark
        stats so the UI can display a fair apples-to-apples comparison.

        Only peers with actual event data (total_events > 0) are included
        in averages and distributions.  The current user is excluded from
        the peer roster to avoid self-comparison bias.
        """
        perf_dir = self._get_perf_dir(year, quarter)
        peers_dir = perf_dir / "peers"
        if not peers_dir.exists():
            return {}

        self_username = self._collector.get_jira_username()
        peers_config = self._load_peers_config()
        pc_cfg = get_peer_comparable_config()

        benchmarks = compute_peer_benchmarks(
            peers_dir,
            peers_config,
            pc_cfg,
            self_username,
        )
        if not benchmarks:
            return {}

        peers_dir.mkdir(parents=True, exist_ok=True)
        with open(peers_dir / "benchmarks.json", "w", encoding="utf-8") as f:
            json.dump(benchmarks, f, indent=2)

        return benchmarks

    async def _handle_collect_peer(self, **kwargs) -> dict:
        """Collect data for a single peer engineer."""
        username = kwargs.get("username", "")
        date_str = kwargs.get("date", "")
        if not username:
            return {"success": False, "error": "username is required"}

        peers_config = self._load_peers_config()
        peer_info = None
        peer_level = ""
        for level_key, peer_list in peers_config.items():
            for peer in peer_list:
                if peer["username"] == username:
                    peer_info = peer
                    peer_level = level_key
                    break
            if peer_info:
                break

        if not peer_info:
            return {"success": False, "error": f"Peer '{username}' not found in config"}

        try:
            target = date.fromisoformat(date_str) if date_str else date.today()
        except ValueError:
            target = date.today()

        try:
            loop = asyncio.get_event_loop()
            daily_data = await loop.run_in_executor(
                None,
                lambda: self._collector.collect_for_date(
                    target, user_override=peer_info, level_override=peer_level
                ),
            )

            year = target.year
            quarter = (target.month - 1) // 3 + 1
            await loop.run_in_executor(
                None, self._update_peer_summary, username, peer_level, year, quarter
            )

            return {
                "success": True,
                "username": username,
                "level": peer_level,
                "date": target.isoformat(),
                "event_count": len(daily_data.get("events", [])),
                "daily_total": daily_data.get("daily_total", 0),
            }
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error("Failed to collect peer data for %s: %s", username, e)
            return {"success": False, "error": str(e)}

    async def _handle_collect_peers(self, **kwargs) -> dict:
        """Collect data for all configured peers for the current quarter.

        When backfill=True, launches a background task and returns immediately
        so the caller can poll progress via get_peer_backfill_progress.

        Optional filters (only used when backfill=True):
          sources:    list of data sources to collect, e.g. ["jira","gitlab"].
                      None / empty means all sources.
          usernames:  list of peer usernames to limit to.
                      None / empty means all peers.
          date_start: ISO date string for range start (inclusive).
          date_end:   ISO date string for range end (inclusive).
        """
        date_str = kwargs.get("date", "")
        backfill = kwargs.get("backfill", False)

        sources = kwargs.get("sources") or None
        usernames = kwargs.get("usernames") or None
        date_start = kwargs.get("date_start", "")
        date_end = kwargs.get("date_end", "")

        try:
            target = date.fromisoformat(date_str) if date_str else date.today()
        except ValueError:
            target = date.today()

        peers_config = self._load_peers_config()
        if not peers_config:
            return {"success": False, "error": "No peers configured"}

        if backfill:
            if self._peer_backfill_progress["running"]:
                return {
                    "success": False,
                    "error": "Peer backfill already running",
                    "progress": self._peer_backfill_progress,
                }
            self._peer_backfill_task = asyncio.create_task(
                self._run_peer_backfill(
                    peers_config,
                    target,
                    sources=sources,
                    usernames=usernames,
                    date_start=date_start,
                    date_end=date_end,
                )
            )
            label_parts = []
            if sources:
                label_parts.append(f"sources={sources}")
            if usernames:
                label_parts.append(f"peers={usernames}")
            if date_start or date_end:
                label_parts.append(
                    f"range={date_start or 'q-start'}..{date_end or 'today'}"
                )
            scope = ", ".join(label_parts) if label_parts else "all"
            return {
                "success": True,
                "async": True,
                "message": f"Peer backfill started ({scope})",
            }

        return await self._collect_peers_sync(peers_config, [target], sources=sources)

    def _ensure_strategy_and_hierarchy(self, year: int, quarter: int) -> None:
        """Load strategy index and hierarchy cache if not already set."""
        if not self._collector.strategy_index:
            emails_dir = self._get_executive_emails_dir(year, quarter)
            self._collector.strategy_index = build_strategy_context_index(emails_dir)
        if not self._collector.hierarchy_cache:
            perf_dir = self._get_perf_dir(year, quarter)
            cache_file = perf_dir / "jira_hierarchy_cache.json"
            if cache_file.exists():
                try:
                    with open(cache_file, encoding="utf-8") as f:
                        self._collector.hierarchy_cache = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to load hierarchy cache: %s", e)
                    self._collector.hierarchy_cache = {}

    async def _collect_peers_sync(
        self,
        peers_config: dict[str, list[dict]],
        dates_to_collect: list[date],
        sources: list[str] | None = None,
    ) -> dict:
        """Synchronous peer collection (for daily / single-date collection)."""
        loop = asyncio.get_event_loop()
        target = dates_to_collect[0]
        year = target.year
        quarter = (target.month - 1) // 3 + 1

        self._ensure_strategy_and_hierarchy(year, quarter)

        results: list[dict] = []
        total_events = 0

        for level_key, peer_list in peers_config.items():
            for peer in peer_list:
                username = peer["username"]
                peer_events = 0
                for d in dates_to_collect:
                    try:
                        daily_data = await loop.run_in_executor(
                            None,
                            lambda _d=d, _p=peer, _l=level_key, _s=sources: self._collector.collect_for_date(
                                _d, user_override=_p, level_override=_l, sources=_s
                            ),
                        )
                        peer_events += len(daily_data.get("events", []))
                    except (
                        OSError,
                        json.JSONDecodeError,
                        KeyError,
                        ValueError,
                        TypeError,
                    ) as e:
                        logger.debug("Peer %s date %s failed: %s", username, d, e)

                await loop.run_in_executor(
                    None, self._update_peer_summary, username, level_key, year, quarter
                )
                total_events += peer_events
                results.append(
                    {
                        "username": username,
                        "level": level_key,
                        "total_events": peer_events,
                    }
                )

        await loop.run_in_executor(None, self._update_peer_benchmarks, year, quarter)

        return {
            "success": True,
            "peers_processed": sum(len(pl) for pl in peers_config.values()),
            "backfill": False,
            "total_events": total_events,
            "results": results,
        }

    async def _run_peer_backfill(  # noqa: C901
        self,
        peers_config: dict[str, list[dict]],
        target: date,
        *,
        sources: list[str] | None = None,
        usernames: list[str] | None = None,
        date_start: str = "",
        date_end: str = "",
    ) -> None:
        """Background task: backfill peer data for the quarter with progress.

        Granular filters let callers re-collect specific slices without a
        full scrub:
          sources   – only re-collect these data sources (git/jira/gitlab/github/gdrive/meeting)
          usernames – only process these peers
          date_start/date_end – restrict to a date range within the quarter
        """
        year = target.year
        quarter = (target.month - 1) // 3 + 1
        loop = asyncio.get_event_loop()
        start_time = time.monotonic()

        src_set = set(sources) if sources else None
        filter_info = build_filter_label(sources, usernames, date_start, date_end)

        self._peer_backfill_cancelled = False
        self._peer_backfill_progress.update(
            {
                "running": True,
                "phase": "resolve_github",
                "phase_detail": "Resolving GitHub usernames...",
                "total_peers": 0,
                "completed_peers": 0,
                "current_peer": "resolving GitHub usernames...",
                "current_level": "",
                "total_days": 0,
                "completed_days": 0,
                "errors": [],
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "elapsed_seconds": 0,
                "total_events": 0,
                "cancelled": False,
                "phases_completed": [],
                "sources": sources or [],
                "filter_info": filter_info,
            }
        )

        try:
            from services.stats.org_parser import resolve_github_usernames

            peers_config = await loop.run_in_executor(
                None, resolve_github_usernames, peers_config
            )
            logger.info("GitHub username resolution completed before backfill")
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.warning("GitHub username resolution failed (non-blocking): %s", e)

        self._peer_backfill_progress["phases_completed"].append("resolve_github")

        if self._peer_backfill_cancelled:
            self._peer_backfill_progress.update(
                {"running": False, "cancelled": True, "phase": "cancelled"}
            )
            return

        all_weekdays = get_weekdays_in_quarter_range(
            year, quarter, date_start, date_end
        )

        all_peers = [
            (level_key, peer)
            for level_key, peer_list in peers_config.items()
            for peer in peer_list
        ]
        if usernames:
            uname_set = set(usernames)
            all_peers = [(lk, p) for lk, p in all_peers if p["username"] in uname_set]

        total_peers = len(all_peers)
        total_days = len(all_weekdays)

        self._peer_backfill_progress.update(
            {
                "total_peers": total_peers,
                "current_peer": "",
                "total_days": total_days,
            }
        )

        self._ensure_strategy_and_hierarchy(year, quarter)

        perf_dir = self._get_perf_dir(year, quarter)
        for _level_key, peer in all_peers:
            if not src_set or "gitlab" in src_set:
                gl_user = peer.get("gitlab_username", "")
                if gl_user:
                    cache = perf_dir / f"gitlab_event_cache_{gl_user}.json"
                    if cache.exists():
                        with self._collector._gitlab_mem_lock:
                            self._collector._gitlab_mem_cache.pop(str(cache), None)
                        cache.unlink()
            if not src_set or "github" in src_set:
                gh_user = peer.get("github_username", "")
                if gh_user:
                    cache = perf_dir / f"github_cache_{gh_user}.json"
                    if cache.exists():
                        with self._collector._github_mem_lock:
                            self._collector._github_mem_cache.pop(str(cache), None)
                        cache.unlink()

        prefetch_count = 0
        if not src_set or src_set & {"gitlab", "github", "jira"}:
            self._peer_backfill_progress.update(
                {
                    "phase": "prefetch",
                    "phase_detail": "Pre-fetching quarter caches...",
                    "current_peer": "pre-fetching quarter caches...",
                }
            )
            for pf_idx, (_, peer) in enumerate(all_peers):
                if self._peer_backfill_cancelled:
                    self._peer_backfill_progress.update(
                        {"running": False, "cancelled": True, "phase": "cancelled"}
                    )
                    return
                pf_user = peer["username"]
                try:
                    if not src_set or "gitlab" in src_set:
                        gl_u = peer.get("gitlab_username", "")
                        if gl_u:
                            await loop.run_in_executor(
                                None,
                                lambda _u=gl_u: self._collector.get_gitlab_cache(
                                    year, quarter, username_override=_u
                                ),
                            )
                    if not src_set or "github" in src_set:
                        gh_u = peer.get("github_username", "")
                        if gh_u:
                            await loop.run_in_executor(
                                None,
                                lambda _u=gh_u: self._collector.get_github_cache(
                                    year, quarter, username_override=_u
                                ),
                            )
                    if not src_set or "jira" in src_set:
                        jira_u = peer.get("jira_username", "")
                        if jira_u:
                            await loop.run_in_executor(
                                None,
                                lambda _u=jira_u: self._collector.prefetch_jira_quarter(
                                    _u, year, quarter
                                ),
                            )
                    prefetch_count += 1
                except (
                    OSError,
                    json.JSONDecodeError,
                    KeyError,
                    ValueError,
                    TypeError,
                ) as e:
                    logger.warning("Pre-fetch failed for %s: %s", pf_user, e)
                self._peer_backfill_progress.update(
                    {
                        "current_peer": f"pre-fetching caches... {pf_idx+1}/{len(all_peers)}",
                        "elapsed_seconds": int(time.monotonic() - start_time),
                    }
                )
            logger.info(
                "Pre-fetched quarter caches for %d/%d peers in %ds",
                prefetch_count,
                len(all_peers),
                int(time.monotonic() - start_time),
            )
            self._peer_backfill_progress["phases_completed"].append("prefetch")

        if self._peer_backfill_cancelled:
            self._peer_backfill_progress.update(
                {"running": False, "cancelled": True, "phase": "cancelled"}
            )
            return

        if not src_set or "gdrive" in src_set:
            self._peer_backfill_progress.update(
                {
                    "phase": "index_gdrive",
                    "phase_detail": "Indexing shared drives...",
                    "current_peer": "indexing shared drives...",
                }
            )
            try:
                from services.stats.gdrive_collector import (
                    _get_shared_drive_ids,
                    ensure_shared_drive_index,
                )

                _drive_ids = _get_shared_drive_ids()
                await loop.run_in_executor(
                    None,
                    lambda: ensure_shared_drive_index(
                        perf_dir=perf_dir,
                        drive_ids=_drive_ids,
                        target=all_weekdays[0] if all_weekdays else date.today(),
                    ),
                )
                logger.info(
                    "Shared drive index built in %ds",
                    int(time.monotonic() - start_time),
                )
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                ValueError,
                TypeError,
            ) as e:
                logger.warning("Shared drive index failed (non-blocking): %s", e)
            self._peer_backfill_progress["phases_completed"].append("index_gdrive")

        if self._peer_backfill_cancelled:
            self._peer_backfill_progress.update(
                {"running": False, "cancelled": True, "phase": "cancelled"}
            )
            return

        if not src_set or "meeting" in src_set:
            self._peer_backfill_progress.update(
                {
                    "phase": "index_meetings",
                    "phase_detail": "Indexing meeting attendance...",
                    "current_peer": "indexing meeting attendance...",
                }
            )
            try:
                from services.stats.meeting_collector import ensure_meeting_peer_index

                await loop.run_in_executor(
                    None,
                    lambda: ensure_meeting_peer_index(
                        perf_dir=perf_dir,
                        target=all_weekdays[0] if all_weekdays else date.today(),
                    ),
                )
                logger.info(
                    "Meeting peer index built in %ds",
                    int(time.monotonic() - start_time),
                )
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                ValueError,
                TypeError,
            ) as e:
                logger.warning("Meeting peer index failed (non-blocking): %s", e)
            self._peer_backfill_progress["phases_completed"].append("index_meetings")

        if self._peer_backfill_cancelled:
            self._peer_backfill_progress.update(
                {"running": False, "cancelled": True, "phase": "cancelled"}
            )
            return

        self._peer_backfill_progress.update(
            {
                "phase": "collecting",
                "phase_detail": "Collecting peer data...",
            }
        )

        parallel_peers = get_merged_config().get(
            "backfill_parallel_peers",
            DEFAULT_GLOBALS["backfill_parallel_peers"],
        )
        sem = asyncio.Semaphore(parallel_peers)
        completed_peers_count = 0
        total_events = 0
        _progress_lock = asyncio.Lock()

        async def _process_peer(
            peer_idx: int,
            level_key: str,
            peer: dict,
        ) -> int:
            nonlocal completed_peers_count, total_events
            username = peer["username"]

            async with sem:
                if src_set and "jira" in src_set:
                    jira_user = peer.get("jira_username", "")
                    if jira_user:
                        cache_key = f"{jira_user}:{year}:Q{quarter}"
                        with self._collector._jira_quarter_lock:
                            self._collector._jira_quarter_cache.pop(cache_key, None)

                peer_repos = None
                if not src_set or "git" in src_set:
                    peer_repos = await loop.run_in_executor(
                        None,
                        lambda _p=peer: self._collector.prepare_peer_repos(
                            _p, year, quarter
                        ),
                    )

                peer_events = 0
                peers_daily_dir = perf_dir / "peers" / username / "daily"
                for _day_idx, d in enumerate(all_weekdays):
                    if self._peer_backfill_cancelled:
                        return 0

                    existing_file = peers_daily_dir / f"{d.isoformat()}.json"
                    if existing_file.exists():
                        try:
                            with open(existing_file, encoding="utf-8") as _ef:
                                existing = json.load(_ef)
                            if existing.get("events"):
                                peer_events += len(existing["events"])
                                continue
                        except (json.JSONDecodeError, OSError) as exc:
                            logger.debug(
                                "Skipped existing peer daily file due to: %s", exc
                            )
                            pass

                    try:

                        def _collect(
                            _d=d, _p=peer, _l=level_key, _s=sources, _r=peer_repos
                        ):
                            return self._collector.collect_for_date(
                                _d,
                                user_override=_p,
                                level_override=_l,
                                sources=_s,
                                peer_repos=_r,
                            )

                        daily_data = await loop.run_in_executor(None, _collect)
                        peer_events += len(daily_data.get("events", []))
                    except (
                        OSError,
                        json.JSONDecodeError,
                        KeyError,
                        ValueError,
                        TypeError,
                    ) as e:
                        async with _progress_lock:
                            if (
                                len(self._peer_backfill_progress["errors"])
                                < MAX_PEER_BACKFILL_ERRORS
                            ):
                                self._peer_backfill_progress["errors"].append(
                                    f"{username}/{d}: {e}"
                                )

                await loop.run_in_executor(
                    None, self._update_peer_summary, username, level_key, year, quarter
                )

                async with _progress_lock:
                    completed_peers_count += 1
                    total_events += peer_events
                    self._peer_backfill_progress.update(
                        {
                            "completed_peers": completed_peers_count,
                            "total_events": total_events,
                            "current_peer": username,
                            "current_level": level_key,
                            "completed_days": len(all_weekdays),
                            "elapsed_seconds": int(time.monotonic() - start_time),
                        }
                    )

                logger.info(
                    "Peer backfill %d/%d: %s (%s) -- %d events",
                    completed_peers_count,
                    total_peers,
                    username,
                    level_key,
                    peer_events,
                )
                return peer_events

        try:
            tasks = [_process_peer(idx, lk, p) for idx, (lk, p) in enumerate(all_peers)]
            await asyncio.gather(*tasks)

            if self._peer_backfill_cancelled:
                self._peer_backfill_progress.update(
                    {"running": False, "cancelled": True, "phase": "cancelled"}
                )
                return

            self._peer_backfill_progress["phases_completed"].append("collecting")
            self._peer_backfill_progress.update(
                {
                    "phase": "benchmarks",
                    "phase_detail": "Updating benchmarks...",
                }
            )

            await loop.run_in_executor(
                None, self._update_peer_benchmarks, year, quarter
            )
            self._peer_backfill_progress["phases_completed"].append("benchmarks")
            self._peer_backfill_progress["phase"] = "complete"
            logger.info(
                "Peer backfill complete: %d peers, %d events in %ds (filter: %s)",
                total_peers,
                total_events,
                int(time.monotonic() - start_time),
                filter_info,
            )
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error("Peer backfill failed: %s", e)
            self._peer_backfill_progress["errors"].append(f"Fatal: {e}")
            self._peer_backfill_progress["phase"] = "error"
        finally:
            self._peer_backfill_progress["running"] = False
            self._peer_backfill_progress["elapsed_seconds"] = int(
                time.monotonic() - start_time
            )

    async def _handle_get_peer_backfill_progress(self, **kwargs) -> dict:
        """Return current peer backfill progress for the UI."""
        return {"success": True, **self._peer_backfill_progress}

    async def _handle_cancel_backfill(self, **kwargs) -> dict:
        """Cancel a running peer backfill."""
        if not self._peer_backfill_progress.get("running"):
            return {"success": True, "message": "No backfill running"}

        self._peer_backfill_cancelled = True
        if self._peer_backfill_task and not self._peer_backfill_task.done():
            self._peer_backfill_task.cancel()

        self._peer_backfill_progress.update(
            {
                "running": False,
                "cancelled": True,
                "phase": "cancelled",
                "phase_detail": "Cancelled by user",
            }
        )
        logger.info("Peer backfill cancelled by user")
        return {"success": True, "message": "Backfill cancelled"}

    async def _handle_scrub_data(self, **kwargs) -> dict:
        """Scrub all collected performance data for the current quarter.

        Nukes the entire perf_dir and parent quarter caches, resets all
        in-memory caches.  After scrub the UI should show a blank slate.
        """
        import shutil

        if self._peer_backfill_progress.get("running"):
            await self._handle_cancel_backfill()

        now = datetime.now()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or ((now.month - 1) // 3 + 1)

        perf_dir = self._get_perf_dir(year, quarter)
        quarter_dir = perf_dir.parent  # e.g. .../2026/q1/

        deleted: dict[str, int] = {}

        # Wipe the entire perf_dir (daily/, peers/, questions.json,
        # summary.json, caches, anstrat, reports, sender files - everything)
        if perf_dir.exists():
            count = sum(1 for _ in perf_dir.rglob("*") if _.is_file())
            shutil.rmtree(perf_dir)
            perf_dir.mkdir(parents=True, exist_ok=True)
            deleted["perf_dir_files"] = count

        # Wipe quarter-level caches that live outside perf_dir
        quarter_cache_patterns = [
            "gdrive_shared_drive_cache.json",
            "gdrive_shared_drive_user_index.json",
            "meeting_contributions_cache.json",
            "meeting_peer_index_cache.json",
        ]
        for pattern in quarter_cache_patterns:
            for f in quarter_dir.glob(pattern):
                f.unlink()
                deleted[f.name] = deleted.get(f.name, 0) + 1

        # Wipe executive emails dir (may be inside or beside perf_dir)
        emails_dir = self._get_executive_emails_dir(year, quarter)
        if emails_dir.exists():
            count = sum(1 for f in emails_dir.glob("*") if f.is_file())
            shutil.rmtree(emails_dir)
            deleted["executive_email_files"] = count

        # Reset ALL in-memory caches
        with self._collector._gitlab_mem_lock:
            self._collector._gitlab_mem_cache.clear()
        with self._collector._github_mem_lock:
            self._collector._github_mem_cache.clear()
        with self._collector._jira_quarter_lock:
            self._collector._jira_quarter_cache.clear()

        self._collector.strategy_index = {}
        self._collector.hierarchy_cache = {}

        # Flush the daemon's own file cache so stale data isn't served
        self._stats_cache.clear()
        self._last_modified.clear()

        total = sum(deleted.values())
        logger.info("Scrubbed %d items from %s Q%d: %s", total, year, quarter, deleted)

        return {
            "success": True,
            "message": f"Scrubbed {total} items from {year} Q{quarter}",
            "deleted": deleted,
            "year": year,
            "quarter": quarter,
        }

    async def _handle_rescore_peers(self, **kwargs) -> dict:
        """Re-enrich and re-score all peer daily files without re-collecting.

        Mirrors evaluate_all but operates on peers/{username}/daily/ dirs.
        Useful after scoring config changes or hierarchy/strategy updates.
        """
        now = datetime.now()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or ((now.month - 1) // 3 + 1)
        usernames_filter = kwargs.get("usernames") or None

        perf_dir = self._get_perf_dir(year, quarter)
        peers_dir = perf_dir / "peers"
        if not peers_dir.exists():
            return {"success": True, "files_updated": 0, "peers_updated": 0}

        loop = asyncio.get_event_loop()

        emails_dir = self._get_executive_emails_dir(year, quarter)
        strategy_index = build_strategy_context_index(emails_dir)
        cache_file = perf_dir / "jira_hierarchy_cache.json"
        hierarchy_cache: dict = {}
        if cache_file.exists():
            try:
                with open(cache_file, encoding="utf-8") as f:
                    hierarchy_cache = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load hierarchy cache: %s", e)
                pass
        self._collector.hierarchy_cache = hierarchy_cache
        self._collector.strategy_index = strategy_index

        def _rescore_peers() -> tuple[int, int]:
            eff_defs, min_sig, daily_cap, _ = get_effective_defs()
            files_updated = 0
            peers_updated = 0

            for peer_path in sorted(peers_dir.iterdir()):
                if not peer_path.is_dir():
                    continue
                username = peer_path.name
                if usernames_filter and username not in usernames_filter:
                    continue
                daily_dir = peer_path / "daily"
                if not daily_dir.exists():
                    continue

                peer_changed = False
                for daily_file in sorted(daily_dir.glob("*.json")):
                    try:
                        with open(daily_file, encoding="utf-8") as f:
                            data = json.load(f)
                    except (json.JSONDecodeError, OSError) as e:
                        logger.warning("Failed to read daily file for rescore: %s", e)
                        continue

                    events = data.get("events", [])
                    for ev in events:
                        self._collector._enrich_event(ev, eff_defs, min_sig)

                    deduped = dedup_events_by_jira_key(
                        events, get_peer_comparable_config()
                    )
                    daily_points = compute_daily_points(
                        deduped, daily_cap, get_source_daily_caps()
                    )

                    data["daily_points"] = daily_points
                    data["daily_total"] = sum(daily_points.values())
                    data["re_evaluated_at"] = datetime.now().isoformat()
                    with open(daily_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    files_updated += 1
                    peer_changed = True

                if peer_changed:
                    peers_updated += 1

            return files_updated, peers_updated

        files_updated, peers_updated = await loop.run_in_executor(None, _rescore_peers)

        peers_config = self._load_peers_config()
        if peers_config:
            for level_key, peer_list in peers_config.items():
                for peer in peer_list:
                    username = peer["username"]
                    if usernames_filter and username not in usernames_filter:
                        continue
                    peer_daily = peers_dir / username / "daily"
                    if peer_daily.exists():
                        await loop.run_in_executor(
                            None,
                            self._update_peer_summary,
                            username,
                            level_key,
                            year,
                            quarter,
                        )

        await loop.run_in_executor(None, self._update_peer_benchmarks, year, quarter)

        return {
            "success": True,
            "files_updated": files_updated,
            "peers_updated": peers_updated,
            "quarter": f"Q{quarter} {year}",
        }

    async def _handle_resolve_github_usernames(self, **kwargs) -> dict:
        """Resolve GitHub usernames for all peers in the roster."""
        try:
            from services.stats.org_parser import resolve_github_usernames

            peers_config = self._load_peers_config()
            if not peers_config:
                return {"success": False, "error": "No peers configured"}
            loop = asyncio.get_event_loop()
            resolved = await loop.run_in_executor(
                None, resolve_github_usernames, peers_config
            )
            total = sum(len(pl) for pl in resolved.values())
            changed = sum(
                1
                for pl in resolved.values()
                for p in pl
                if p["github_username"] != p["username"]
            )
            return {
                "success": True,
                "total_peers": total,
                "resolved_different": changed,
            }
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error("GitHub username resolution failed: %s", e)
            return {"success": False, "error": str(e)}

    async def _handle_get_peer_benchmarks(self, **kwargs) -> dict:
        """Return aggregated peer benchmarks for the UI."""
        now = datetime.now()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or ((now.month - 1) // 3 + 1)

        perf_dir = self._get_perf_dir(year, quarter)
        benchmarks_file = perf_dir / "peers" / "benchmarks.json"

        if benchmarks_file.exists():
            try:
                with open(benchmarks_file, encoding="utf-8") as f:
                    benchmarks = json.load(f)
                return {"success": True, "benchmarks": benchmarks}
            except (json.JSONDecodeError, OSError) as e:
                return {"success": False, "error": f"Failed to read benchmarks: {e}"}

        return {
            "success": True,
            "benchmarks": {"levels": {}, "last_updated": None},
        }

    def _get_user_competency_pct(self) -> dict[str, int]:
        """Load user's current competency percentages from summary."""
        summary = self._load_file(get_performance_summary_path())
        if summary:
            return summary.get("cumulative_percentage", {})
        return {}

    def _get_user_event_counts(self) -> dict[str, int]:
        """Count events by source from current quarter's daily files."""
        now = datetime.now()
        perf_dir = self._get_perf_dir(now.year, (now.month - 1) // 3 + 1)
        daily_dir = perf_dir / "daily"
        counts: dict[str, int] = {}
        if daily_dir.exists():
            for f in daily_dir.glob("*.json"):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    for ev in data.get("events", []):
                        src = ev.get("source", "unknown")
                        counts[src] = counts.get(src, 0) + 1
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read daily file for event counts: %s", e)
                    continue
        return counts

    def _load_benchmarks_levels(self) -> dict:
        """Load peer benchmark levels data."""
        now = datetime.now()
        perf_dir = self._get_perf_dir(now.year, (now.month - 1) // 3 + 1)
        bf = perf_dir / "peers" / "benchmarks.json"
        if bf.exists():
            try:
                with open(bf, encoding="utf-8") as f:
                    return json.load(f).get("levels", {})
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load benchmarks.json: %s", e)
                pass
        return {}
