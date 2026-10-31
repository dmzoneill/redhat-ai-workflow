"""Jira issue hierarchy (ANSTRAT -> Epic -> Issue) for the stats daemon.

Split out of ``services/stats/daemon.py``; ``StatsDaemon`` mixes
``IssueHierarchyMixin`` in, so the ``get_issue_hierarchy`` D-Bus method is
unchanged.
"""

import asyncio
import logging
import os
import re
from pathlib import Path

from services.stats.day_detail import DayDetailMixin
from services.stats.handler_utils import (
    HIERARCHY_CACHE_NAME,
    find_issue_keys,
    load_daily_files,
    load_issue_cache,
    now_local,
    quarter_of,
    write_json,
)

logger = logging.getLogger(__name__)

KEYWORD_PATTERNS = (
    "billing",
    "mock",
    "test",
    "ci/cd",
    "pipeline",
    "deploy",
    "api",
    "fix",
    "feat",
    "refactor",
    "config",
    "auth",
    "grafana",
    "monitoring",
    "alert",
    "release",
    "review",
    "docs",
    "migration",
    "performance",
    "security",
    "integration",
)

# ``key : value`` lines from ``rh-issue view-issue``; the key cannot contain ':',
# so matching up to the first ':' and stripping afterwards is linear-time.
_FIELD_RE = re.compile(r"^([a-z][a-z_ /]+):(.*)$", re.IGNORECASE)
_ISSUE_FIELDS = ("summary", "status", "issue_type", "issuetype")
_EPIC_FIELDS = ("epic_link", "epic", "parent")
_MAX_ISSUES_FETCHED = 30


class RhIssueError(RuntimeError):
    """``rh-issue`` exited non-zero or timed out."""


# Failures of one ``rh-issue`` call: missing binary, bad output, exit or timeout.
_RH_ERRORS = (OSError, ValueError, RhIssueError)


async def run_rh_issue(args: list[str], timeout: float, env: dict[str, str]) -> str:
    """Run ``rh-issue`` without blocking the event loop and return its stdout."""
    proc = await asyncio.create_subprocess_exec(
        "rh-issue",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RhIssueError(f"rh-issue {args[0]} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise RhIssueError(f"rh-issue {args[0]} exited with {proc.returncode}")
    return stdout.decode()


def parse_fields(output: str) -> list[tuple[str, str]]:
    """Return ``(field, value)`` pairs from ``rh-issue view-issue`` output."""
    fields: list[tuple[str, str]] = []
    for line in output.split("\n"):
        m = _FIELD_RE.match(line.strip())
        if m:
            fields.append((m.group(1).strip().lower().replace(" ", "_"), m.group(2).strip()))
    return fields


def parse_issue(key: str, output: str) -> dict[str, str]:
    """Build the cached info for a story/task from ``view-issue`` output."""
    info: dict[str, str] = {"key": key, "type": "story"}
    for field, val in parse_fields(output):
        if field in _ISSUE_FIELDS:
            info[field.replace("issuetype", "issue_type")] = val
        if field in _EPIC_FIELDS:
            info["epic"] = val
        if field == "component/s":
            info["component"] = val
    if "summary" not in info:
        for line in output.split("\n"):
            if key in line:
                info["summary"] = line.split(key)[-1].strip(": ")[:100]
                break
    return info


def parse_epic(key: str, output: str) -> dict[str, str]:
    """Build the cached info for an epic from ``view-issue`` output."""
    info: dict[str, str] = {"key": key, "issue_type": "Epic"}
    for field, val in parse_fields(output):
        if field == "summary":
            info["summary"] = val
        if field == "component/s":
            info["component"] = val
    return info


def parse_anstrat_search(output: str, issue_info: dict[str, dict]) -> list[str]:
    """Add ANSTRAT rows from ``rh-issue search`` output; return the keys found."""
    anstrat_keys = re.findall(r"(ANSTRAT-\d+)", output)
    for line in output.split("\n"):
        for ak in anstrat_keys:
            if ak in line and ak not in issue_info:
                parts = line.split("|")
                if len(parts) >= 5:
                    issue_info[ak] = {
                        "key": ak,
                        "issue_type": parts[1].strip(),
                        "summary": parts[4].strip()[:100],
                    }
    return anstrat_keys


def extract_keywords(titles: list[str]) -> list[str]:
    """Return the known work keywords that appear in any of *titles*."""
    found: set[str] = set()
    for title in titles:
        lowered = title.lower()
        found.update(kw for kw in KEYWORD_PATTERNS if kw in lowered)
    return sorted(found)


def collect_issue_keys(daily_dir: Path) -> dict[str, dict]:
    """Total points, titles and event counts per issue key in the daily files."""
    issue_keys: dict[str, dict] = {}
    for _, data in load_daily_files(daily_dir):
        if data is None:
            continue
        for ev in data.get("events", []):
            title = ev.get("title", "")
            pts = sum(ev.get("points", {}).values())
            for key in find_issue_keys(title):
                entry = issue_keys.setdefault(key, {"points": 0, "titles": [], "event_count": 0})
                entry["points"] += pts
                entry["event_count"] += 1
                if title not in entry["titles"]:
                    entry["titles"].append(title[:120])
    return issue_keys


def _first_component(issue_info: dict[str, dict]) -> str | None:
    for info in issue_info.values():
        component = str(info.get("component", ""))
        if component and component != "None":
            return component
    return None


async def _fetch_issues(keys: list[str], issue_info: dict[str, dict], env: dict[str, str]) -> None:
    for key in keys[:_MAX_ISSUES_FETCHED]:
        try:
            issue_info[key] = parse_issue(key, await run_rh_issue(["view-issue", key], 15, env))
        except _RH_ERRORS as e:
            logger.debug("Failed to fetch %s: %s", key, e)


async def _fetch_epics(epic_keys: set[str], issue_info: dict[str, dict], env: dict[str, str]) -> None:
    for epic_key in epic_keys:
        if epic_key in issue_info:
            continue
        try:
            issue_info[epic_key] = parse_epic(epic_key, await run_rh_issue(["view-issue", epic_key], 15, env))
        except _RH_ERRORS as e:
            logger.debug("Failed to fetch epic %s: %s", epic_key, e)


async def _search_anstrats(issue_info: dict[str, dict], env: dict[str, str]) -> list[str]:
    component = _first_component(issue_info)
    jql = (
        f'project = ANSTRAT AND component = "{component}"'
        if component
        else 'project = ANSTRAT AND summary ~ "Automation Analytics"'
    )
    try:
        output = await run_rh_issue(["search", jql, "--max-results", "50"], 30, env)
    except _RH_ERRORS as e:
        logger.debug("Failed to search ANSTRATs: %s", e)
        return []
    return parse_anstrat_search(output, issue_info)


async def _link_epics(
    epic_keys: set[str], anstrat_keys: list[str], issue_info: dict[str, dict], env: dict[str, str]
) -> None:
    unmapped = {k for k in epic_keys if not issue_info.get(k, {}).get("parent_initiative")}
    epic_list_str = ", ".join(sorted(epic_keys))
    for anstrat_key in anstrat_keys:
        if not unmapped:
            break
        jql = f'"Parent Link" = {anstrat_key} AND key in ({epic_list_str})'
        try:
            output = await run_rh_issue(["search", jql, "--max-results", "20"], 20, env)
        except _RH_ERRORS as e:
            logger.debug("Failed to query children of %s: %s", anstrat_key, e)
            continue
        for child in re.findall(r"(AAP-\d+)", output):
            issue_info.setdefault(child, {"key": child})["parent_initiative"] = anstrat_key
            unmapped.discard(child)


async def refresh_issue_info(issue_keys: dict[str, dict], issue_info: dict[str, dict]) -> None:
    """Fill *issue_info* from Jira: issues, their epics and the parent ANSTRATs."""
    env = {**os.environ, "HOME": str(Path.home())}
    await _fetch_issues([k for k in issue_keys if k.startswith("AAP-")], issue_info, env)

    epic_keys = {info.get("epic", "") for info in issue_info.values() if info.get("epic", "").startswith("AAP-")}
    await _fetch_epics(epic_keys, issue_info, env)
    if epic_keys:
        anstrat_keys = await _search_anstrats(issue_info, env)
        await _link_epics(epic_keys, anstrat_keys, issue_info, env)


def _empty_node(key: str, summary: str, node_type: str) -> dict:
    return {
        "key": key,
        "summary": summary,
        "type": node_type,
        "points": 0,
        "event_count": 0,
        "keywords": [],
        "children": [],
    }


def _by_points(nodes) -> list[dict]:
    return sorted(nodes, key=lambda x: -x["points"])


def attach_epics(epics: dict[str, dict], strategies: dict[str, dict], issue_info: dict[str, dict]) -> list[dict]:
    """Attach epics under their parent ANSTRAT; return the epics with no parent."""
    unattached = []
    for epic_key, epic_node in epics.items():
        epic_info = issue_info.get(epic_key, {})
        parent = epic_info.get("parent_initiative", "") or epic_info.get("epic", "") or epic_info.get("parent", "")
        if parent and parent.startswith("ANSTRAT-"):
            if parent not in strategies:
                strategies[parent] = _empty_node(parent, issue_info.get(parent, {}).get("summary", parent), "strategy")
            strategies[parent]["children"].append(epic_node)
            strategies[parent]["points"] += epic_node["points"]
        else:
            unattached.append(epic_node)
    return unattached


def build_tree(issue_keys: dict[str, dict], issue_info: dict[str, dict]) -> dict:
    """Group issues under epics and epics under ANSTRAT strategies."""
    strategies: dict[str, dict] = {}
    epics: dict[str, dict] = {}
    uncategorized: list[dict] = []

    for key, data in issue_keys.items():
        info = issue_info.get(key, {})
        node = {
            "key": key,
            "summary": info.get("summary", ""),
            "type": info.get("issue_type", "story").lower(),
            "points": data["points"],
            "event_count": data["event_count"],
            "keywords": extract_keywords(data["titles"]),
            "children": [],
        }
        epic_key = info.get("epic", "")
        if key.startswith("ANSTRAT-"):
            node["type"] = "strategy"
            strategies[key] = node
        elif epic_key:
            if epic_key not in epics:
                epic_summary = issue_info.get(epic_key, {}).get("summary", epic_key)
                epics[epic_key] = _empty_node(epic_key, epic_summary, "epic")
            epics[epic_key]["children"].append(node)
            epics[epic_key]["points"] += node["points"]
        else:
            uncategorized.append(node)

    unattached_epics = attach_epics(epics, strategies, issue_info)

    strat_list = _by_points(strategies.values())
    for strategy in strat_list:
        strategy["children"] = _by_points(strategy["children"])
        for epic in strategy["children"]:
            epic["children"] = _by_points(epic["children"])
    unattached_epics = _by_points(unattached_epics)
    for epic in unattached_epics:
        epic["children"] = _by_points(epic["children"])

    return {
        "strategies": strat_list,
        "unattached_epics": unattached_epics,
        "uncategorized": _by_points(uncategorized),
    }


class IssueHierarchyMixin(DayDetailMixin):
    """``get_issue_hierarchy`` D-Bus handler."""

    async def _handle_get_issue_hierarchy(self, **kwargs) -> dict:
        """Extract issue keys from daily data and build hierarchy tree."""
        return await self.issue_hierarchy(refresh=kwargs.get("refresh_from_jira", False))

    async def issue_hierarchy(self, refresh: bool = False) -> dict:
        """ANSTRAT -> Epic -> Issue tree for this quarter; *refresh* re-reads Jira."""
        now = now_local()
        year, quarter = now.year, quarter_of(now)

        perf_dir = self.perf_dir(year, quarter)
        cache_file = perf_dir / HIERARCHY_CACHE_NAME
        issue_keys = await asyncio.to_thread(collect_issue_keys, self.daily_dir(year, quarter))

        cached: dict = {} if refresh else await asyncio.to_thread(load_issue_cache, cache_file)
        issue_info: dict[str, dict] = cached.get("issues", {})

        if refresh and issue_keys:
            await refresh_issue_info(issue_keys, issue_info)
            perf_dir.mkdir(parents=True, exist_ok=True)
            cache_data = {"issues": issue_info, "updated": now_local().isoformat()}
            await asyncio.to_thread(write_json, cache_file, cache_data)

        return {
            "success": True,
            **build_tree(issue_keys, issue_info),
            "total_issues": len(issue_keys),
            "cached": not refresh and bool(cached),
        }
