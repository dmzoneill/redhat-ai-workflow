"""Hierarchy resolution and report export mixin for StatsDaemon."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from html import unescape as html_unescape
from pathlib import Path

from server.utils import run_cmd_sync
from services.stats.anstrat_sync import sync_anstrat_ownership
from services.stats.email_parser import (
    get_executive_senders,
    parse_email_text,
    set_executive_senders,
)
from services.stats.strategy import build_strategy_context_index

MAX_HIERARCHY_KEYS_PER_BATCH = 30
JIRA_QUERY_TIMEOUT = 30
MAX_DESCRIPTION_LENGTH = 500
MAX_SUMMARY_LENGTH = 100
MAX_TEXT_PREVIEW_LENGTH = 300

logger = logging.getLogger(__name__)


def _run_rh_issue(args: list[str], timeout: int = 15) -> str:
    ok, out = run_cmd_sync(["rh-issue"] + args, timeout=timeout)
    if not ok:
        raise RuntimeError(out)
    return out


class HierarchyMixin:
    """Jira issue hierarchy, report export, and executive email methods."""

    @staticmethod
    def _refresh_fetch_aap_issues(
        issue_keys: dict[str, dict],
        issue_info: dict[str, dict],
    ) -> None:
        aap_keys = [k for k in issue_keys if k.startswith("AAP-")]
        for key in aap_keys[:MAX_HIERARCHY_KEYS_PER_BATCH]:
            try:
                result = _run_rh_issue(["view-issue", key])
                info: dict[str, str] = {"key": key, "type": "story"}
                desc_lines: list[str] = []
                in_description = False
                for line in result.split("\n"):
                    m = re.match(
                        r"^([a-z][a-z_ /]+?)\s*:\s*(.*)$",
                        line.strip(),
                        re.IGNORECASE,
                    )
                    if m:
                        in_description = False
                        field = m.group(1).strip().lower().replace(" ", "_")
                        val = m.group(2).strip()
                        if field in (
                            "summary",
                            "status",
                            "issue_type",
                            "issuetype",
                        ):
                            info[field.replace("issuetype", "issue_type")] = val
                        if field in ("epic_link", "epic", "parent"):
                            info["epic"] = val
                        if field == "component/s":
                            info["component"] = val
                        if field == "reporter":
                            info["reporter"] = val
                        if field in ("assignee", "assigned_to"):
                            info["assignee"] = val
                        if field == "description":
                            in_description = True
                            if val:
                                desc_lines.append(val)
                    elif in_description:
                        desc_lines.append(line.strip())
                if desc_lines:
                    info["description"] = " ".join(desc_lines)[:MAX_DESCRIPTION_LENGTH]
                if "summary" not in info:
                    for line in result.split("\n"):
                        if key in line:
                            info["summary"] = line.split(key)[-1].strip(": ")[
                                :MAX_SUMMARY_LENGTH
                            ]
                            break
                if "summary" in info:
                    info["summary"] = html_unescape(info["summary"])
                issue_info[key] = info
            except Exception as e:
                logger.debug("Failed to fetch %s: %s", key, e)

    @staticmethod
    def _refresh_fetch_epics(
        epic_keys_set: set[str],
        issue_info: dict[str, dict],
    ) -> None:
        for epic_key in epic_keys_set:
            if epic_key not in issue_info:
                try:
                    result = _run_rh_issue(["view-issue", epic_key])
                    einfo: dict[str, str] = {"key": epic_key, "issue_type": "Epic"}
                    for line in result.split("\n"):
                        m = re.match(
                            r"^([a-z][a-z_ /]+?)\s*:\s*(.*)$",
                            line.strip(),
                            re.IGNORECASE,
                        )
                        if m:
                            field = m.group(1).strip().lower().replace(" ", "_")
                            val = m.group(2).strip()
                            if field == "summary":
                                einfo["summary"] = html_unescape(val)
                            if field == "component/s":
                                einfo["component"] = val
                            if field in ("parent", "parent_link"):
                                if val.startswith("ANSTRAT-"):
                                    einfo["parent_initiative"] = val
                    issue_info[epic_key] = einfo
                except Exception as e:
                    logger.debug("Failed to fetch epic %s: %s", epic_key, e)

    @staticmethod
    def _refresh_discover_user_anstrats(
        issue_info: dict[str, dict],
    ) -> set[str]:
        user_assigned_anstrats: set[str] = set()
        try:
            result = _run_rh_issue(
                [
                    "search",
                    "project = ANSTRAT AND assignee = currentUser() "
                    "AND status not in (Closed, Done, Resolved) "
                    "ORDER BY updated DESC",
                    "--max-results",
                    "20",
                ],
                timeout=JIRA_QUERY_TIMEOUT,
            )
            for line in result.split("\n"):
                found = re.findall(r"(ANSTRAT-\d+)", line)
                for ak in found:
                    user_assigned_anstrats.add(ak)
                    if ak not in issue_info:
                        parts = line.split("|")
                        if len(parts) >= 5:
                            issue_info[ak] = {
                                "key": ak,
                                "issue_type": (
                                    parts[1].strip() if len(parts) > 1 else "Initiative"
                                ),
                                "summary": html_unescape(
                                    parts[4].strip()[:MAX_SUMMARY_LENGTH]
                                    if len(parts) > 4
                                    else ak
                                ),
                            }
        except Exception as e:
            logger.debug("Failed to search user-assigned ANSTRATs: %s", e)
        return user_assigned_anstrats

    @staticmethod
    def _refresh_map_unmapped_epics(
        epic_keys_set: set[str],
        issue_info: dict[str, dict],
        user_assigned_anstrats: set[str],
        hierarchy_anstrats: set[str],
    ) -> None:
        unmapped_epics = {
            k
            for k in epic_keys_set
            if not issue_info.get(k, {}).get("parent_initiative")
        }
        if not unmapped_epics:
            return
        epic_list_str = ", ".join(sorted(epic_keys_set))
        for anstrat_key in user_assigned_anstrats:
            if not unmapped_epics:
                break
            try:
                jql = f'"Parent Link" = {anstrat_key}' f" AND key in ({epic_list_str})"
                result = _run_rh_issue(
                    ["search", jql, "--max-results", "20"],
                    timeout=20,
                )
                child_epics = re.findall(r"(AAP-\d+)", result)
                for ce in child_epics:
                    if ce in issue_info:
                        issue_info[ce]["parent_initiative"] = anstrat_key
                    else:
                        issue_info[ce] = {
                            "key": ce,
                            "parent_initiative": anstrat_key,
                        }
                    unmapped_epics.discard(ce)
                    hierarchy_anstrats.add(anstrat_key)
            except Exception as e:
                logger.debug("Failed to query children of %s: %s", anstrat_key, e)

    @staticmethod
    def _refresh_discover_child_epics(
        issue_info: dict[str, dict],
        relevant_anstrats: set[str],
    ) -> None:
        for anstrat_key in relevant_anstrats:
            try:
                jql = f'"Parent Link" = {anstrat_key}' f" AND assignee = currentUser()"
                result = _run_rh_issue(
                    ["search", jql, "--max-results", "20"],
                    timeout=20,
                )
                for line in result.split("\n"):
                    child_keys = re.findall(r"(AAP-\d+)", line)
                    for ce in child_keys:
                        if ce in issue_info:
                            if not issue_info[ce].get("parent_initiative"):
                                issue_info[ce]["parent_initiative"] = anstrat_key
                        else:
                            parts = line.split("|")
                            issue_info[ce] = {
                                "key": ce,
                                "parent_initiative": anstrat_key,
                                "issue_type": (
                                    parts[1].strip() if len(parts) > 1 else "Epic"
                                ),
                                "summary": (
                                    parts[4].strip()[:MAX_SUMMARY_LENGTH]
                                    if len(parts) > 4
                                    else ce
                                ),
                            }
            except Exception as e:
                logger.debug("Failed to query user children of %s: %s", anstrat_key, e)

    @staticmethod
    def _refresh_save_hierarchy_cache(
        issue_info: dict[str, dict],
        perf_dir: Path,
    ) -> None:
        perf_dir.mkdir(parents=True, exist_ok=True)
        cache_file = perf_dir / "jira_hierarchy_cache.json"
        cache_data = {"issues": issue_info, "updated": datetime.now().isoformat()}
        with open(cache_file, "w", encoding="utf-8") as fh:
            json.dump(cache_data, fh, indent=2)

    @staticmethod
    def _refresh_issue_hierarchy_from_jira(
        issue_keys: dict[str, dict],
        issue_info: dict[str, dict],
        perf_dir: Path,
    ) -> dict[str, dict]:
        """Fetch issue metadata from Jira via subprocess (blocking I/O)."""
        HierarchyMixin._refresh_fetch_aap_issues(issue_keys, issue_info)

        epic_keys_set: set[str] = set()
        for info_val in issue_info.values():
            epic_key = info_val.get("epic", "")
            if epic_key and epic_key.startswith("AAP-"):
                epic_keys_set.add(epic_key)

        HierarchyMixin._refresh_fetch_epics(epic_keys_set, issue_info)
        user_assigned_anstrats = HierarchyMixin._refresh_discover_user_anstrats(
            issue_info
        )

        hierarchy_anstrats: set[str] = set()
        for info_val in issue_info.values():
            parent = info_val.get("parent_initiative", "")
            if parent.startswith("ANSTRAT-"):
                hierarchy_anstrats.add(parent)

        HierarchyMixin._refresh_map_unmapped_epics(
            epic_keys_set, issue_info, user_assigned_anstrats, hierarchy_anstrats
        )
        relevant_anstrats = user_assigned_anstrats | hierarchy_anstrats
        HierarchyMixin._refresh_discover_child_epics(issue_info, relevant_anstrats)

        issue_info["_user_relevant_anstrats"] = {
            "keys": sorted(user_assigned_anstrats | hierarchy_anstrats)
        }

        HierarchyMixin._refresh_save_hierarchy_cache(issue_info, perf_dir)
        return issue_info

    @staticmethod
    def _hierarchy_collect_issue_keys(
        daily_dir: Path,
        comp_to_pillar: dict[str, str],
    ) -> dict[str, dict]:
        issue_keys: dict[str, dict] = {}
        if not daily_dir.exists():
            return issue_keys
        for f in sorted(daily_dir.glob("*.json")):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
                for ev in data.get("events", []):
                    title = ev.get("title", "")
                    ev_points = ev.get("points", {})
                    pts = sum(ev_points.values())
                    ev_scope = ev.get("scope", "commit")
                    ev_strategy = ev.get("strategy_aligned", False)
                    ev_strat_names = ev.get("strategy_priorities", [])

                    pillar_pts: dict[str, int] = {
                        "technical": 0,
                        "leadership": 0,
                        "mentorship": 0,
                        "delivery": 0,
                    }
                    for comp_id, comp_pts in ev_points.items():
                        pillar = comp_to_pillar.get(comp_id, "technical")
                        pillar_pts[pillar] += comp_pts

                    keys_in_title = re.findall(r"((?:AAP|ANSTRAT)-\d+)", title)
                    for key in keys_in_title:
                        if key not in issue_keys:
                            issue_keys[key] = {
                                "points": 0,
                                "titles": [],
                                "event_count": 0,
                                "strategy_aligned": False,
                                "strategy_names": set(),
                                "pillar_points": {
                                    "technical": 0,
                                    "leadership": 0,
                                    "mentorship": 0,
                                    "delivery": 0,
                                },
                                "scope_points": {},
                            }
                        ik = issue_keys[key]
                        ik["points"] += pts
                        ik["event_count"] += 1
                        if title not in ik["titles"]:
                            ik["titles"].append(title[:120])
                        if ev_strategy:
                            ik["strategy_aligned"] = True
                        for sn in ev_strat_names:
                            ik["strategy_names"].add(sn)
                        for p, v in pillar_pts.items():
                            ik["pillar_points"][p] += v
                        ik["scope_points"][ev_scope] = (
                            ik["scope_points"].get(ev_scope, 0) + pts
                        )
            except Exception as e:
                logger.warning("Failed to process daily event for hierarchy: %s", e)
                continue
        return issue_keys

    @staticmethod
    def _hierarchy_extract_keywords(titles: list[str]) -> list[str]:
        kw_patterns = [
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
        ]
        found = set()
        for t in titles:
            t_lower = t.lower()
            for kw in kw_patterns:
                if kw in t_lower:
                    found.add(kw)
        return sorted(found)

    @staticmethod
    def _hierarchy_build_tree(
        issue_keys: dict[str, dict],
        issue_info: dict[str, dict],
    ) -> tuple[dict[str, dict], dict[str, dict], list[dict], list[dict]]:
        strategies: dict[str, dict] = {}
        epics: dict[str, dict] = {}
        uncategorized: list[dict] = []

        def _empty_pillar() -> dict:
            return {"technical": 0, "leadership": 0, "mentorship": 0, "delivery": 0}

        def _summary_from_titles(titles: list[str]) -> str:
            for t in titles:
                cleaned = re.sub(r"(?:AAP|ANSTRAT)-\d+\s*[-:]\s*", "", t).strip()
                if cleaned and len(cleaned) > 5:
                    return html_unescape(cleaned[:MAX_SUMMARY_LENGTH])
            return ""

        for key, data in issue_keys.items():
            jira_summary = issue_info.get(key, {}).get("summary", "")
            if jira_summary:
                jira_summary = html_unescape(jira_summary)
            if not jira_summary:
                jira_summary = _summary_from_titles(data.get("titles", []))
            node = {
                "key": key,
                "summary": jira_summary,
                "type": issue_info.get(key, {}).get("issue_type", "story").lower(),
                "points": data["points"],
                "event_count": data["event_count"],
                "keywords": HierarchyMixin._hierarchy_extract_keywords(data["titles"]),
                "strategy_aligned": data.get("strategy_aligned", False),
                "strategy_names": data.get("strategy_names", []),
                "pillar_points": data.get("pillar_points", _empty_pillar()),
                "scope_points": data.get("scope_points", {}),
                "children": [],
            }
            if key.startswith("ANSTRAT-"):
                strategies[key] = node
                node["type"] = "strategy"
                node["strategy_aligned"] = True
            else:
                epic_key = issue_info.get(key, {}).get("epic", "")
                if epic_key:
                    if epic_key not in epics:
                        epics[epic_key] = {
                            "key": epic_key,
                            "summary": html_unescape(
                                issue_info.get(epic_key, {}).get("summary", epic_key)
                            ),
                            "type": "epic",
                            "points": 0,
                            "event_count": 0,
                            "keywords": [],
                            "strategy_aligned": False,
                            "strategy_names": [],
                            "pillar_points": _empty_pillar(),
                            "scope_points": {},
                            "children": [],
                        }
                    epics[epic_key]["children"].append(node)
                    epics[epic_key]["points"] += node["points"]
                    if node["strategy_aligned"]:
                        epics[epic_key]["strategy_aligned"] = True
                    for p in ("technical", "leadership", "mentorship", "delivery"):
                        epics[epic_key]["pillar_points"][p] += node[
                            "pillar_points"
                        ].get(p, 0)
                    for sc, sv in node["scope_points"].items():
                        epics[epic_key]["scope_points"][sc] = (
                            epics[epic_key]["scope_points"].get(sc, 0) + sv
                        )
                else:
                    uncategorized.append(node)

        unattached_epics = []
        for epic_key, epic_node in epics.items():
            attached = False
            epic_info = issue_info.get(epic_key, {})
            parent = epic_info.get("parent_initiative", "")
            if not parent:
                parent = epic_info.get("epic", "") or epic_info.get("parent", "")
            if parent and parent.startswith("ANSTRAT-"):
                if parent not in strategies:
                    anstrat_info = issue_info.get(parent, {})
                    strategies[parent] = {
                        "key": parent,
                        "summary": html_unescape(anstrat_info.get("summary", parent)),
                        "type": "strategy",
                        "points": 0,
                        "event_count": 0,
                        "keywords": [],
                        "strategy_aligned": True,
                        "strategy_names": [],
                        "pillar_points": _empty_pillar(),
                        "scope_points": {},
                        "children": [],
                    }
                strategies[parent]["children"].append(epic_node)
                strategies[parent]["points"] += epic_node["points"]
                if epic_node.get("strategy_aligned"):
                    strategies[parent]["strategy_aligned"] = True
                for p in ("technical", "leadership", "mentorship", "delivery"):
                    strategies[parent]["pillar_points"][p] += epic_node.get(
                        "pillar_points", {}
                    ).get(p, 0)
                for sc, sv in epic_node.get("scope_points", {}).items():
                    strategies[parent]["scope_points"][sc] = (
                        strategies[parent]["scope_points"].get(sc, 0) + sv
                    )
                attached = True
            if not attached:
                unattached_epics.append(epic_node)

        relevant_set = set(
            issue_info.get("_user_relevant_anstrats", {}).get("keys", [])
        )
        for info_key, info_val in issue_info.items():
            if (
                info_key.startswith("ANSTRAT-")
                and info_key not in strategies
                and info_key in relevant_set
            ):
                strategies[info_key] = {
                    "key": info_key,
                    "summary": info_val.get("summary", info_key),
                    "type": "strategy",
                    "points": 0,
                    "event_count": 0,
                    "keywords": [],
                    "strategy_aligned": True,
                    "strategy_names": [],
                    "pillar_points": _empty_pillar(),
                    "scope_points": {},
                    "children": [],
                }

        return strategies, epics, uncategorized, unattached_epics

    @staticmethod
    def _hierarchy_sort_and_aggregate(
        strategies: dict[str, dict],
        uncategorized: list[dict],
        unattached_epics: list[dict],
        issue_keys: dict[str, dict],
    ) -> tuple[list[dict], list[dict], list[dict], dict]:
        strat_list = sorted(strategies.values(), key=lambda x: -x["points"])
        for s in strat_list:
            s["children"] = sorted(s["children"], key=lambda x: -x["points"])
            for e in s["children"]:
                e["children"] = sorted(e["children"], key=lambda x: -x["points"])

        unattached_epics = sorted(unattached_epics, key=lambda x: -x["points"])
        for e in unattached_epics:
            e["children"] = sorted(e["children"], key=lambda x: -x["points"])

        uncategorized = sorted(uncategorized, key=lambda x: -x["points"])

        total_points = sum(ik["points"] for ik in issue_keys.values())
        aligned_points = sum(
            ik["points"] for ik in issue_keys.values() if ik.get("strategy_aligned")
        )
        agg_scope: dict[str, int] = {}
        agg_pillar: dict[str, int] = {
            "technical": 0,
            "leadership": 0,
            "mentorship": 0,
            "delivery": 0,
        }
        agg_tags: dict[str, int] = {}
        for ik in issue_keys.values():
            for sc, sv in ik.get("scope_points", {}).items():
                agg_scope[sc] = agg_scope.get(sc, 0) + sv
            for p in ("technical", "leadership", "mentorship", "delivery"):
                agg_pillar[p] += ik.get("pillar_points", {}).get(p, 0)
            for kw in HierarchyMixin._hierarchy_extract_keywords(ik.get("titles", [])):
                agg_tags[kw] = agg_tags.get(kw, 0) + 1

        summary = {
            "total_points": total_points,
            "aligned_points": aligned_points,
            "unaligned_points": total_points - aligned_points,
            "alignment_pct": (
                round(aligned_points / total_points * 100) if total_points else 0
            ),
            "scope_points": agg_scope,
            "pillar_points": agg_pillar,
            "tag_counts": dict(sorted(agg_tags.items(), key=lambda x: -x[1])),
        }
        return strat_list, unattached_epics, uncategorized, summary

    async def _handle_get_issue_hierarchy(self, **kwargs) -> dict:
        """Extract issue keys from daily data and build hierarchy tree."""
        from services.stats.scorer import COMPETENCY_DEFS

        refresh = kwargs.get("refresh_from_jira", False)
        now = datetime.now()
        year = now.year
        quarter = (now.month - 1) // 3 + 1

        perf_dir = self._get_perf_dir(year, quarter)
        daily_dir = self._get_daily_dir(year, quarter)
        cache_file = perf_dir / "jira_hierarchy_cache.json"

        comp_to_pillar: dict[str, str] = {}
        pillar_short: dict[str, str] = {
            "Technical Contribution": "technical",
            "Leadership": "leadership",
            "Mentorship": "mentorship",
            "End-to-End Delivery": "delivery",
        }
        for cid, defn in COMPETENCY_DEFS.items():
            cat = defn.get("category", "Technical Contribution")
            comp_to_pillar[cid] = pillar_short.get(cat, "technical")

        emails_dir = self._get_executive_emails_dir(year, quarter)
        strategy_index = build_strategy_context_index(emails_dir)
        strat_issue_keys = strategy_index.get("all_issue_keys", {})

        issue_keys = HierarchyMixin._hierarchy_collect_issue_keys(
            daily_dir, comp_to_pillar
        )
        for key, ik in issue_keys.items():
            if not ik["strategy_aligned"] and key in strat_issue_keys:
                ik["strategy_aligned"] = True
                for sn in strat_issue_keys[key]:
                    ik["strategy_names"].add(sn)
            ik["strategy_names"] = sorted(ik["strategy_names"])

        cached: dict = {}
        if cache_file.exists() and not refresh:
            try:
                with open(cache_file, encoding="utf-8") as fh:
                    cached = json.load(fh)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load hierarchy cache: %s", e)
                pass

        issue_info: dict[str, dict] = cached.get("issues", {})

        if refresh and issue_keys:
            issue_info = await asyncio.to_thread(
                self._refresh_issue_hierarchy_from_jira,
                issue_keys,
                issue_info,
                perf_dir,
            )

        strategies, _, uncategorized, unattached_epics = (
            HierarchyMixin._hierarchy_build_tree(issue_keys, issue_info)
        )
        strat_list, unattached_epics, uncategorized, summary = (
            HierarchyMixin._hierarchy_sort_and_aggregate(
                strategies, uncategorized, unattached_epics, issue_keys
            )
        )

        return {
            "success": True,
            "strategies": strat_list,
            "unattached_epics": unattached_epics,
            "uncategorized": uncategorized,
            "total_issues": len(issue_keys),
            "cached": not refresh and bool(cached),
            "summary": summary,
        }

    async def _handle_export_report(self, **kwargs) -> dict:
        """Generate and export a quarterly performance report."""
        now = datetime.now()
        year = now.year
        quarter = (now.month - 1) // 3 + 1
        fmt = kwargs.get("format", "markdown")

        perf_dir = self._get_perf_dir(year, quarter)
        daily_dir = self._get_daily_dir(year, quarter)

        summary = self._load_file(perf_dir / "summary.json") or {}

        all_events: list[dict] = []
        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    all_events.extend(data.get("events", []))
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read daily file for report: %s", e)
                    continue

        if fmt == "json":
            report = {
                "quarter": f"Q{quarter} {year}",
                "summary": summary,
                "total_events": len(all_events),
                "events": all_events,
            }
            report_file = perf_dir / f"report_q{quarter}_{year}.json"
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)

        elif fmt == "pdf":
            return await self._export_pdf_report(
                year,
                quarter,
                now,
                perf_dir,
                summary,
                all_events,
            )

        else:
            lines = [
                f"# Q{quarter} {year} Quarterly Connection Report",
                "",
                f"**Generated:** {now.strftime('%Y-%m-%d %H:%M')}",
                f"**Overall Score:** {summary.get('overall_percentage', 0)}%",
                f"**Total Events:** {len(all_events)}",
                "",
                "## Competency Progress",
                "",
            ]
            for comp, pct in sorted(
                summary.get("cumulative_percentage", {}).items(),
                key=lambda x: -x[1],
            ):
                name = comp.replace("_", " ").title()
                pts = summary.get("cumulative_points", {}).get(comp, 0)
                lines.append(f"- **{name}**: {pct}% ({pts} pts)")

            if summary.get("gaps"):
                lines.append("\n## Areas Needing Attention\n")
                for gap in summary["gaps"]:
                    lines.append(f"- {gap.replace('_', ' ').title()}")

            if summary.get("highlights"):
                lines.append("\n## Highlights\n")
                for h in summary["highlights"]:
                    lines.append(f"- {h}")

            lines.append("")
            report_file = perf_dir / f"report_q{quarter}_{year}.md"
            with open(report_file, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

        return {
            "success": True,
            "path": str(report_file),
            "format": fmt,
            "event_count": len(all_events),
        }

    async def _export_pdf_report(
        self,
        year: int,
        quarter: int,
        now: datetime,
        perf_dir: Path,
        summary: dict,
        all_events: list[dict],
    ) -> dict:
        """Gather all data and render the PDF report."""
        from services.stats.report_helpers import (
            generate_calendar_html,
            generate_competency_bars_html,
            generate_mindmap_svg,
            generate_sunburst_svg,
            render_pdf,
            score_color,
        )

        quarter_label = f"Q{quarter} {year}"
        overall_pct = summary.get("overall_percentage", 0)
        competencies = summary.get("cumulative_percentage", {})

        comp_dict: dict[str, dict] = {}
        for comp_id, pct in competencies.items():
            pts = summary.get("cumulative_points", {}).get(comp_id, 0)
            comp_dict[comp_id] = {"percentage": pct, "points": pts}

        hierarchy = None
        try:
            hier_result = await self._handle_get_issue_hierarchy(
                refresh_from_jira=False
            )
            if hier_result.get("strategies") or hier_result.get("unattached_epics"):
                hierarchy = hier_result
        except Exception as e:
            logger.warning("Failed to load hierarchy for PDF: %s", e)

        comp_evidence: dict = {}
        gap_suggestions_data: dict = {}
        try:
            ev_result = await self._handle_get_competency_evidence()
            comp_evidence = ev_result.get("competency_evidence", {})
            gap_suggestions_data = ev_result.get("gap_suggestions", {})
        except Exception as e:
            logger.warning("Failed to load competency evidence for PDF: %s", e)

        captured_days: list[dict] = []
        try:
            cap_result = await self._handle_get_captured_days()
            captured_days = cap_result.get("days", [])
        except Exception as e:
            logger.warning("Failed to load captured days for PDF: %s", e)

        strategy_data: dict | None = None
        try:
            emails_result = await self._handle_list_executive_emails()
            emails = emails_result.get("emails", [])
            if emails:
                latest = emails[0]
                email_id = latest.get("email_id", "")
                emails_dir = self._get_executive_emails_dir(year, quarter)
                cache_file = emails_dir / f"{email_id}.json"
                parsed_email = None
                if cache_file.exists():
                    with open(cache_file, encoding="utf-8") as fh:
                        parsed_email = json.load(fh)

                map_result = await self._handle_map_deliverables(email_id=email_id)

                strategy_data = {
                    "parsed_email": parsed_email,
                    "mappings": map_result.get("mappings", []),
                    "priority_coverage": map_result.get("priority_coverage", []),
                    "coverage_summary": map_result.get("coverage_summary"),
                }
        except Exception as e:
            logger.warning("Failed to load strategy data for PDF: %s", e)

        questions_summary = summary.get("questions_summary") or []

        sunburst_svg = (
            generate_sunburst_svg(comp_dict, overall_pct) if comp_dict else ""
        )
        mindmap_svg = (
            generate_mindmap_svg(hierarchy, quarter_label) if hierarchy else ""
        )

        calendar_html = generate_calendar_html(captured_days, year, quarter)
        competency_bars_html = generate_competency_bars_html(comp_dict)

        days_captured = len(captured_days)
        total_issues = hierarchy.get("total_issues", 0) if hierarchy else 0

        peer_benchmarks_data: dict | None = None
        peer_radar_svg = ""
        peer_bars_html = ""
        peer_volume_html = ""
        benchmarks_file = perf_dir / "peers" / "benchmarks.json"
        if benchmarks_file.exists():
            try:
                with open(benchmarks_file, encoding="utf-8") as bf:
                    peer_benchmarks_data = json.load(bf)
                from services.stats.report_helpers import (
                    generate_grouped_bars_html,
                    generate_radar_svg,
                    generate_volume_table_html,
                )

                user_profile = {
                    k: v.get("percentage", 0) if isinstance(v, dict) else 0
                    for k, v in comp_dict.items()
                }
                peer_profiles = {
                    lk: ld.get("avg_competency_pct", {})
                    for lk, ld in peer_benchmarks_data.get("levels", {}).items()
                }
                peer_radar_svg = generate_radar_svg(user_profile, peer_profiles)
                peer_bars_html = generate_grouped_bars_html(
                    comp_dict, peer_benchmarks_data.get("levels", {})
                )
                user_volume: dict[str, int] = {}
                for ev in all_events:
                    src = ev.get("source", "unknown")
                    user_volume[src] = user_volume.get(src, 0) + 1
                peer_volumes = {
                    lk: ld.get("avg_event_counts_by_source", {})
                    for lk, ld in peer_benchmarks_data.get("levels", {}).items()
                }
                peer_volume_html = generate_volume_table_html(user_volume, peer_volumes)
            except Exception as e:
                logger.debug("Failed to load peer benchmarks for report: %s", e)

        template_data = {
            "quarter": quarter_label,
            "generated_at": now.strftime("%Y-%m-%d %H:%M"),
            "overall_pct": overall_pct,
            "score_color": score_color(overall_pct),
            "day_of_quarter": summary.get("day_of_quarter", 0),
            "total_events": len(all_events),
            "days_captured": days_captured,
            "total_issues": total_issues,
            "num_competencies": len(comp_dict),
            "sunburst_svg": sunburst_svg,
            "mindmap_svg": mindmap_svg,
            "calendar_html": calendar_html,
            "competency_bars_html": competency_bars_html,
            "competencies": comp_dict,
            "highlights": summary.get("highlights", []),
            "gaps_list": [g.replace("_", " ").title() for g in summary.get("gaps", [])],
            "hierarchy": hierarchy,
            "competency_evidence": comp_evidence,
            "gap_suggestions": gap_suggestions_data,
            "questions_summary": questions_summary,
            "strategy_data": strategy_data,
            "all_events": all_events,
            "peer_benchmarks": peer_benchmarks_data,
            "peer_radar_svg": peer_radar_svg,
            "peer_bars_html": peer_bars_html,
            "peer_volume_html": peer_volume_html,
        }

        template_path = Path(__file__).parent / "report_template.html"
        report_file = perf_dir / f"report_q{quarter}_{year}.pdf"

        loop = asyncio.get_event_loop()
        pdf_path = await loop.run_in_executor(
            None,
            render_pdf,
            template_data,
            template_path,
            report_file,
        )

        return {
            "success": True,
            "path": pdf_path,
            "format": "pdf",
            "event_count": len(all_events),
        }

    async def _handle_parse_executive_email(self, **kwargs) -> dict:
        """Parse an executive email and cache the result."""
        import hashlib

        text = kwargs.get("text", "")
        email_id = kwargs.get("email_id", "")

        if not text:
            return {"success": False, "error": "No email text provided"}

        parsed = parse_email_text(text)

        if not email_id:
            email_id = hashlib.sha256(
                text[:MAX_DESCRIPTION_LENGTH].encode()
            ).hexdigest()[:12]

        parsed["email_id"] = email_id
        parsed["parsed_at"] = datetime.now().isoformat()
        parsed["text_preview"] = text[:MAX_TEXT_PREVIEW_LENGTH].replace("\n", " ")

        emails_dir = self._get_executive_emails_dir()
        emails_dir.mkdir(parents=True, exist_ok=True)
        cache_file = emails_dir / f"{email_id}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2)

        return {"success": True, **parsed}

    async def _handle_map_deliverables(self, **kwargs) -> dict:
        """Map user's delivered issues to executive email targets."""
        email_id = kwargs.get("email_id", "")

        emails_dir = self._get_executive_emails_dir()
        if email_id:
            cache_file = emails_dir / f"{email_id}.json"
            if not cache_file.exists():
                return {"success": False, "error": f"Email {email_id} not found"}
            with open(cache_file, encoding="utf-8") as f:
                parsed = json.load(f)
        else:
            if not emails_dir.exists():
                return {"success": False, "error": "No executive emails cached"}
            files = sorted(
                emails_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            if not files:
                return {"success": False, "error": "No executive emails cached"}
            with open(files[0], encoding="utf-8") as f:
                parsed = json.load(f)
            email_id = parsed.get("email_id", files[0].stem)

        hierarchy_result = await self._handle_get_issue_hierarchy(
            refresh_from_jira=False
        )

        user_issues: dict[str, dict] = {}

        def collect_issues(nodes: list, parent_anstrat: str = ""):
            if not isinstance(nodes, list):
                return
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                key = node.get("key", "")
                if key:
                    user_issues[key] = {
                        "key": key,
                        "summary": node.get("summary", ""),
                        "type": node.get("type", ""),
                        "points": node.get("points", 0),
                        "keywords": node.get("keywords", []),
                        "parent_anstrat": parent_anstrat,
                    }
                children = node.get("children", [])
                anstrat = parent_anstrat
                if key.startswith("ANSTRAT-"):
                    anstrat = key
                collect_issues(children, anstrat)

        collect_issues(hierarchy_result.get("strategies", []))
        collect_issues(hierarchy_result.get("unattached_epics", []))
        collect_issues(hierarchy_result.get("uncategorized", []))

        email_issue_keys = set(parsed.get("issue_keys", {}).keys())
        email_priorities = parsed.get("priorities", [])
        email_themes = parsed.get("themes", [])

        mappings: list[dict] = []

        direct_matches = email_issue_keys & set(user_issues.keys())
        for key in sorted(direct_matches):
            ui = user_issues[key]
            contexts = parsed.get("issue_keys", {}).get(key, [])
            mappings.append(
                {
                    "match_type": "direct_key",
                    "confidence": "high",
                    "user_issue": key,
                    "user_summary": ui.get("summary", ""),
                    "user_points": ui.get("points", 0),
                    "email_context": contexts[0] if contexts else "",
                    "priority_name": "",
                }
            )

        email_anstrats = {k for k in email_issue_keys if k.startswith("ANSTRAT-")}
        for issue_key, info in user_issues.items():
            if issue_key in direct_matches:
                continue
            parent = info.get("parent_anstrat", "")
            if parent and parent in email_anstrats:
                contexts = parsed.get("issue_keys", {}).get(parent, [])
                mappings.append(
                    {
                        "match_type": "anstrat_link",
                        "confidence": "high",
                        "user_issue": issue_key,
                        "user_summary": info.get("summary", ""),
                        "user_points": info.get("points", 0),
                        "email_context": contexts[0] if contexts else f"Under {parent}",
                        "priority_name": parent,
                    }
                )

        mapped_keys = {m["user_issue"] for m in mappings}
        for issue_key, info in user_issues.items():
            if issue_key in mapped_keys:
                continue
            user_kws = set(info.get("keywords", []))
            if not user_kws:
                continue
            for theme in email_themes:
                theme_kws = set(theme.get("matched_keywords", []))
                overlap = user_kws & theme_kws
                if overlap:
                    mappings.append(
                        {
                            "match_type": "theme",
                            "confidence": "medium",
                            "user_issue": issue_key,
                            "user_summary": info.get("summary", ""),
                            "user_points": info.get("points", 0),
                            "email_context": f"Theme: {theme['name']} (keywords: {', '.join(overlap)})",
                            "priority_name": theme["name"],
                        }
                    )
                    mapped_keys.add(issue_key)
                    break

        priority_coverage: list[dict] = []
        for prio in email_priorities:
            prio_keys = set(prio.get("issue_keys", []))
            prio_name = prio.get("name", "")
            matching = [
                m
                for m in mappings
                if m.get("priority_name") == prio_name
                or any(k in prio_keys for k in [m["user_issue"]])
                or (
                    m.get("priority_name", "").startswith("ANSTRAT-")
                    and m["priority_name"] in prio_keys
                )
            ]
            direct_prio = prio_keys & set(user_issues.keys())
            status = "covered" if (matching or direct_prio) else "gap"
            priority_coverage.append(
                {
                    "name": prio_name,
                    "context": prio.get("context", "")[:150],
                    "issue_keys": list(prio_keys),
                    "status": status,
                    "matching_issues": [m["user_issue"] for m in matching]
                    + list(direct_prio),
                }
            )

        covered = sum(1 for p in priority_coverage if p["status"] == "covered")
        total_priorities = len(priority_coverage)

        return {
            "success": True,
            "email_id": email_id,
            "mappings": mappings,
            "priority_coverage": priority_coverage,
            "coverage_summary": {
                "total_priorities": total_priorities,
                "covered": covered,
                "gaps": total_priorities - covered,
                "coverage_pct": round(covered / max(total_priorities, 1) * 100),
                "total_user_issues": len(user_issues),
                "mapped_issues": len(mapped_keys),
                "unmapped_issues": len(user_issues) - len(mapped_keys),
            },
            "match_counts": {
                "direct_key": sum(
                    1 for m in mappings if m["match_type"] == "direct_key"
                ),
                "anstrat_link": sum(
                    1 for m in mappings if m["match_type"] == "anstrat_link"
                ),
                "theme": sum(1 for m in mappings if m["match_type"] == "theme"),
            },
        }

    async def _handle_list_executive_emails(self, **kwargs) -> dict:
        """List cached parsed executive emails for the quarter."""
        emails_dir = self._get_executive_emails_dir()
        emails: list[dict] = []

        if emails_dir.exists():
            for f in sorted(
                emails_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            ):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    emails.append(
                        {
                            "email_id": data.get("email_id", f.stem),
                            "sender": data.get("sender", "Unknown"),
                            "sender_email": data.get("sender_email", ""),
                            "subject": data.get("subject", ""),
                            "date": data.get("email_date", ""),
                            "parsed_at": data.get("parsed_at", ""),
                            "text_preview": data.get("text_preview", "")[:150],
                            "total_priorities": data.get("total_priorities", 0),
                            "total_issue_keys": data.get("total_issue_keys", 0),
                            "total_themes": data.get("total_themes", 0),
                        }
                    )
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read executive email cache: %s", e)
                    continue

        return {"success": True, "emails": emails}

    async def _handle_delete_executive_email(self, **kwargs) -> dict:
        """Delete a cached executive email."""
        email_id = kwargs.get("email_id", "")
        if not email_id:
            return {"success": False, "error": "No email_id provided"}

        emails_dir = self._get_executive_emails_dir()
        cache_file = emails_dir / f"{email_id}.json"
        if cache_file.exists():
            cache_file.unlink()
            return {"success": True, "deleted": email_id}
        return {"success": False, "error": f"Email {email_id} not found"}

    async def _handle_get_executive_senders(self, **kwargs) -> dict:
        """Return the configured executive email senders."""
        return {"success": True, "senders": get_executive_senders()}

    async def _handle_set_executive_senders(self, **kwargs) -> dict:
        """Update the executive email senders list in config.json."""
        senders = kwargs.get("senders")
        if senders is None:
            return {"success": False, "error": "No senders provided"}
        if not isinstance(senders, list):
            return {"success": False, "error": "senders must be a list"}
        cleaned = [
            s.strip().lower() for s in senders if isinstance(s, str) and s.strip()
        ]
        if set_executive_senders(cleaned):
            return {"success": True, "senders": cleaned}
        return {"success": False, "error": "Failed to write config.json"}

    async def _handle_sync_anstrat_ownership(self, **kwargs) -> dict:
        """Sync ANSTRAT issue catalog from Jira (passive model, no assignee ownership)."""
        try:
            perf_dir = self._get_perf_dir()
            ownership = await asyncio.to_thread(sync_anstrat_ownership, perf_dir)
            issue_count = len(ownership.get("issues", {}))
            return {
                "success": True,
                "issues": issue_count,
                "last_synced": ownership.get("last_synced"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
