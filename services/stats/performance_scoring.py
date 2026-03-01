"""
Performance scoring helpers - standalone functions for competency point computation.

Extracted from StatsDaemon for reuse and testability. All functions take explicit
parameters instead of depending on daemon state.
"""

import re
from typing import Any

from services.stats.scorer import map_competencies


def _is_work_repo(
    repo: str,
    work_orgs: list[str],
    work_gl_groups: list[str],
    work_repos: list[str],
) -> bool:
    """Return True if a repo belongs to a known work org or project list."""
    if repo in work_repos:
        return True
    for org in work_orgs:
        if repo.startswith(f"{org}/"):
            return True
    for grp in work_gl_groups:
        if repo.startswith(f"{grp}/"):
            return True
    return False


def compute_competency_percentages(
    points: dict[str, int], effective_target: int
) -> dict[str, int]:
    """Convert competency points to percentages capped at 100."""
    return {k: min(round(v / effective_target * 100), 100) for k, v in points.items()}


def compute_daily_points(
    events: list[dict],
    daily_cap: int,
    source_caps: dict[str, int],
    strip_enrichment: bool = False,
) -> dict[str, int]:
    """Aggregate event points into daily competency totals.

    Applies per-competency daily_cap and per-source daily caps to
    prevent any single data source from dominating the daily score.

    When strip_enrichment=True, uses comparable_points() to re-score
    each event without session enrichment text before aggregating.
    """
    daily_points: dict[str, int] = {}
    source_totals: dict[str, int] = {}

    for ev in events:
        src = ev.get("source", "unknown")
        src_cap = source_caps.get(src)
        if src_cap is not None and source_totals.get(src, 0) >= src_cap:
            continue

        pts_dict = comparable_points(ev) if strip_enrichment else ev.get("points", {})

        ev_added = 0
        for comp_id, pts in pts_dict.items():
            current = daily_points.get(comp_id, 0)
            added = min(pts, daily_cap - current)
            daily_points[comp_id] = current + added
            ev_added += added

        if src_cap is not None:
            source_totals[src] = source_totals.get(src, 0) + ev_added

    return daily_points


def comparable_points(ev: dict) -> dict[str, int]:
    """Return event points suitable for peer-comparable scoring.

    If the event was enriched with session narrative
    (extra_classification_text), re-score using the base
    classification text only so the comparison is fair -- peers
    never have session enrichment.
    """
    extra = ev.get("extra_classification_text", "")
    if not extra:
        return ev.get("points", {})

    class_text = ev.get("classification_text", "")
    if extra and extra in class_text:
        class_text = class_text.replace(extra, "").rstrip()

    return map_competencies(
        class_text,
        ev.get("source", ""),
        ev.get("type", ""),
        ev.get("scope", "story"),
        ev.get("role", "assignee"),
        strategy_aligned=ev.get("strategy_aligned", False),
        contribution_type=ev.get("contribution_type"),
        is_cross_team=ev.get("is_cross_team", False),
        review_decision=ev.get("review_decision"),
    )


def normalize_strategy_bonus(
    points: dict[str, int], ev: dict, bonus_multiplier: float = 1.5
) -> dict[str, int]:
    """Remove strategy alignment bonus from event points for fair comparison.

    Peers CAN receive strategy bonuses when their Jira work matches the
    strategy index (built from executive emails).  Stripping the bonus
    from both self and peer scores ensures an apples-to-apples comparison.
    """
    if not ev.get("strategy_aligned"):
        return points
    return {
        comp_id: max(1, round(pts / bonus_multiplier))
        for comp_id, pts in points.items()
    }


def is_personal_repo_event(ev: dict, peer_comparable_config: dict[str, Any]) -> bool:
    """Return True if the event is from a personal/non-work repo.

    Checks git, github, gitlab sources against configured work repos/orgs.
    Used to exclude personal hobby projects from ALL scoring (full + comparable).
    """
    source = ev.get("source", "")
    work_orgs = peer_comparable_config.get("work_github_orgs", [])
    work_gl_groups = peer_comparable_config.get("work_gitlab_groups", [])
    work_repos = peer_comparable_config.get("work_project_repos", [])

    if source in ("github", "gitlab"):
        item_id = ev.get("item_id", "")
        repo = ""
        if "#" in item_id:
            repo = item_id.split("#")[0]
        elif "!" in item_id:
            repo = item_id.split("!")[0]
        if repo and not _is_work_repo(repo, work_orgs, work_gl_groups, work_repos):
            return True

    if source == "git":
        title = ev.get("title", "")
        m = re.match(r"\[([^\]]+)\]", title)
        repo_name = m.group(1) if m else ""
        if repo_name and repo_name not in work_repos:
            return True

    return False


def is_primary_only_event(ev: dict, peer_comparable_config: dict[str, Any]) -> bool:
    """Return True if the event should be excluded from the peer-comparable score.

    Excluded categories (beyond personal repos which are excluded from all scores):
    - Session events (no peer equivalent)
    - Personal GDrive (not shared drive)
    """
    if is_personal_repo_event(ev, peer_comparable_config):
        return True
    source = ev.get("source", "")
    if source == "session":
        return True
    if source == "gdrive" and not ev.get("gdrive_shared_drive"):
        return True
    return False


def process_daily_events_for_summary(
    events: list[dict],
    daily_cap: int,
    source_caps: dict[str, int],
    peer_comparable_config: dict[str, Any],
    strategy_bonus_multiplier: float = 1.5,
) -> tuple[
    dict[str, int],
    dict[str, int],
    int,
    dict[str, int],
    dict[str, int],
]:
    """Process one day's events for no-enrichment and peer-comparable scoring.

    Returns (no_enrichment_daily, peer_comparable_daily, pc_event_count,
             counts_by_source, comparable_counts_by_source).
    """
    max_daily_total = peer_comparable_config.get("max_daily_comparable_total", 0)
    max_meetings_per_day = peer_comparable_config.get("max_meetings_per_day", 3)

    work_events = [
        ev for ev in events if not is_personal_repo_event(ev, peer_comparable_config)
    ]
    deduped = dedup_events_by_jira_key(work_events, peer_comparable_config)
    ne_daily = compute_daily_points(
        deduped, daily_cap, source_caps, strip_enrichment=True
    )

    pc_daily: dict[str, int] = {}
    pc_events = 0
    counts_by_source: dict[str, int] = {}
    comparable_counts_by_source: dict[str, int] = {}
    day_meeting_count = 0

    for ev in work_events:
        src = ev.get("source", "unknown")
        counts_by_source[src] = counts_by_source.get(src, 0) + 1

        if not is_primary_only_event(ev, peer_comparable_config):
            if src == "meeting":
                day_meeting_count += 1
                if day_meeting_count > max_meetings_per_day:
                    continue
            pc_events += 1
            comparable_counts_by_source[src] = (
                comparable_counts_by_source.get(src, 0) + 1
            )
            raw_pts = comparable_points(ev)
            ev_pts = normalize_strategy_bonus(
                raw_pts, ev, bonus_multiplier=strategy_bonus_multiplier
            )
            for comp_id, pts in ev_pts.items():
                current = pc_daily.get(comp_id, 0)
                pc_daily[comp_id] = min(current + pts, daily_cap)

    if max_daily_total and pc_daily:
        pc_day_sum = sum(pc_daily.values())
        if pc_day_sum > max_daily_total:
            scale = max_daily_total / pc_day_sum
            pc_daily = {k: max(1, round(v * scale)) for k, v in pc_daily.items()}

    return (
        ne_daily,
        pc_daily,
        pc_events,
        counts_by_source,
        comparable_counts_by_source,
    )


def dedup_events_by_jira_key(
    events: list[dict], peer_comparable_config: dict[str, Any]
) -> list[dict]:
    """Deduplicate and cap events for fair daily scoring.

    1. Cross-source dedup: keep only the highest-scoring event per Jira key
    2. Meeting cap: keep only the top N meeting events by point value
    """
    max_meetings = peer_comparable_config.get("max_meetings_per_day", 3)

    keyed: dict[str, list[dict]] = {}
    unkeyed: list[dict] = []
    for ev in events:
        item_id = ev.get("item_id", "")
        title = ev.get("title", "")
        jira_key = ""
        if re.match(r"[A-Z]+-\d+$", item_id):
            jira_key = item_id
        else:
            m = re.search(r"([A-Z]+-\d+)", title)
            if m:
                jira_key = m.group(1)
        if jira_key:
            keyed.setdefault(jira_key, []).append(ev)
        else:
            unkeyed.append(ev)
    result = list(unkeyed)
    for _jk, evts in keyed.items():
        best = max(evts, key=lambda e: sum(e.get("points", {}).values()))
        result.append(best)

    meetings = [e for e in result if e.get("source") == "meeting"]
    if len(meetings) > max_meetings:
        meetings.sort(key=lambda e: sum(e.get("points", {}).values()), reverse=True)
        drop = set(id(e) for e in meetings[max_meetings:])
        result = [e for e in result if id(e) not in drop]

    return result
