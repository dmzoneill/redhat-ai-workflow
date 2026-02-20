import json
import logging
import os
import re
import subprocess
from pathlib import Path

from services.stats.scorer import COMPETENCY_DEFS

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "the",
    "and",
    "for",
    "are",
    "with",
    "this",
    "that",
    "from",
    "not",
    "has",
    "was",
    "will",
    "can",
    "all",
    "been",
    "have",
    "into",
    "new",
    "use",
    "its",
    "may",
    "our",
    "but",
    "also",
    "any",
    "each",
    "than",
}


def build_strategy_context_index(emails_dir: Path) -> dict:
    """Load all cached executive emails and build a fast lookup structure.

    Returns a dict with:
      - priorities: list of {name, context, issue_keys, text_keywords}
      - all_issue_keys: {issue_key: [priority_name, ...]}
    """
    if not emails_dir.exists():
        return {"priorities": [], "all_issue_keys": {}}

    all_priorities: dict[str, dict] = {}
    for f in sorted(emails_dir.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue

        for prio in data.get("priorities", []):
            name = prio.get("name", "")
            if not name:
                continue
            key = name.lower()
            if key not in all_priorities:
                combined = f"{name} {prio.get('context', '')}".lower()
                text_keywords = {
                    w for w in re.findall(r"[a-z]{3,}", combined) if w not in STOP_WORDS
                }
                all_priorities[key] = {
                    "name": name,
                    "context": prio.get("context", "")[:300],
                    "issue_keys": list(prio.get("issue_keys", [])),
                    "text_keywords": text_keywords,
                }
            else:
                existing = all_priorities[key]
                for ik in prio.get("issue_keys", []):
                    if ik not in existing["issue_keys"]:
                        existing["issue_keys"].append(ik)

    issue_key_index: dict[str, list[str]] = {}
    for prio in all_priorities.values():
        for ik in prio["issue_keys"]:
            issue_key_index.setdefault(ik, [])
            if prio["name"] not in issue_key_index[ik]:
                issue_key_index[ik].append(prio["name"])

    return {
        "priorities": list(all_priorities.values()),
        "all_issue_keys": issue_key_index,
    }


def match_event_to_strategy(
    item_id: str,
    hierarchy: dict,
    classification_text: str,
    strategy_index: dict,
    min_overlap_words: int = 3,
) -> tuple[bool, list[str]]:
    """Check if an event matches any strategy priority.

    Returns (is_aligned, list_of_matched_priority_names).
    Uses issue-key matching first, then falls back to text overlap.
    """
    if not strategy_index or not strategy_index.get("priorities"):
        return False, []

    matched_names: list[str] = []
    issue_key_index = strategy_index.get("all_issue_keys", {})

    keys_to_check = [item_id]
    epic_key = hierarchy.get("epic_key", "")
    anstrat_key = hierarchy.get("anstrat_key", "")
    if epic_key:
        keys_to_check.append(epic_key)
    if anstrat_key:
        keys_to_check.append(anstrat_key)

    for k in keys_to_check:
        for pname in issue_key_index.get(k, []):
            if pname not in matched_names:
                matched_names.append(pname)

    if matched_names:
        return True, matched_names

    text_words = {
        w
        for w in re.findall(r"[a-z]{3,}", classification_text.lower())
        if w not in STOP_WORDS
    }
    for prio in strategy_index.get("priorities", []):
        overlap = len(text_words & prio.get("text_keywords", set()))
        if overlap >= min_overlap_words:
            if prio["name"] not in matched_names:
                matched_names.append(prio["name"])

    return bool(matched_names), matched_names


def enrich_user_issues_from_jira(
    year: int, quarter: int, user_issues: dict[str, dict]
) -> dict[str, dict]:
    """Query Jira API for ALL user issues in the quarter (any status).

    Merges results into user_issues dict so strategy alignment has full data.
    """
    quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    sm, _ = quarter_starts[quarter]
    q_start = f"{year}-{sm:02d}-01"
    next_q = quarter + 1
    if next_q > 4:
        q_end = f"{year + 1}-01-01"
    else:
        nsm = quarter_starts[next_q][0]
        q_end = f"{year}-{nsm:02d}-01"

    jql = (
        f"assignee = currentUser() AND "
        f'(updatedDate >= "{q_start}" OR createdDate >= "{q_start}") '
        f'AND createdDate <= "{q_end}" '
        f"ORDER BY updated DESC"
    )

    added = 0
    try:
        result = subprocess.run(
            ["rh-issue", "search", jql, "--max-results", "100"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5:
                    key = parts[0]
                    if key.startswith(("AAP-", "ANSTRAT-")) and key not in user_issues:
                        user_issues[key] = {
                            "key": key,
                            "summary": parts[4] if len(parts) > 4 else "",
                            "status": parts[2] if len(parts) > 2 else "",
                            "issue_type": parts[1] if len(parts) > 1 else "",
                            "source": "jira_api",
                        }
                        added += 1
            logger.info(
                f"Enriched with {added} new issues from Jira API "
                f"(total now: {len(user_issues)})"
            )
    except subprocess.TimeoutExpired:
        logger.warning("Jira API query timed out")
    except Exception as e:
        logger.warning(f"Jira API enrichment failed: {e}")

    return user_issues


def get_quarter_gitlab_mrs(year: int, quarter: int) -> list[dict]:
    """Fetch all GitLab MRs authored by user for the quarter via API."""
    import urllib.parse
    import urllib.request

    config_file = Path(__file__).resolve().parents[2] / "config.json"
    try:
        with open(config_file, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:
        return []

    gitlab_host = cfg.get("gitlab", {}).get("host", "gitlab.cee.redhat.com")

    token = os.environ.get("GITLAB_TOKEN", "")
    if not token:
        glab_config = Path.home() / ".config" / "glab-cli" / "config.yml"
        if glab_config.exists():
            try:
                import yaml

                with open(glab_config, encoding="utf-8") as fh:
                    gc = yaml.safe_load(fh)
                for host_data in gc.get("hosts", {}).values():
                    token = host_data.get("token", "")
                    if token:
                        break
            except Exception:
                pass
    if not token:
        logger.warning("No GitLab token found for MR enrichment")
        return []

    username = ""
    try:
        user_url = f"https://{gitlab_host}/api/v4/user"
        user_req = urllib.request.Request(user_url, headers={"PRIVATE-TOKEN": token})
        with urllib.request.urlopen(user_req, timeout=10) as resp:
            user_data = json.loads(resp.read())
            username = user_data.get("username", "")
    except Exception:
        pass
    if not username:
        logger.warning("Could not determine GitLab username")
        return []

    quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    sm, _ = quarter_starts[quarter]
    q_start = f"{year}-{sm:02d}-01T00:00:00Z"
    next_q = quarter + 1
    if next_q > 4:
        q_end = f"{year + 1}-01-01T00:00:00Z"
    else:
        nsm = quarter_starts[next_q][0]
        q_end = f"{year}-{nsm:02d}-01T00:00:00Z"

    repos = cfg.get("repositories", {})
    all_mrs: list[dict] = []
    seen_mr_ids: set[str] = set()

    def _add_mrs(mrs_list: list[dict], repo_name: str) -> None:
        for mr in mrs_list:
            uid = f"{repo_name}:{mr['iid']}"
            if uid in seen_mr_ids:
                continue
            seen_mr_ids.add(uid)
            all_mrs.append(
                {
                    "project": repo_name,
                    "iid": mr["iid"],
                    "title": mr.get("title", ""),
                    "state": mr.get("state", ""),
                    "web_url": mr.get("web_url", ""),
                    "created_at": mr.get("created_at", "")[:10],
                    "description": (mr.get("description") or "")[:200],
                }
            )

    for repo_name, proj_cfg in repos.items():
        gl_path = proj_cfg.get("gitlab", "")
        if not gl_path or gl_path.startswith("github:"):
            continue
        encoded = urllib.parse.quote(gl_path, safe="")

        url = (
            f"https://{gitlab_host}/api/v4/projects/{encoded}/merge_requests"
            f"?scope=all&author_username={username}"
            f"&created_after={q_start}&created_before={q_end}&per_page=100"
        )
        req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                _add_mrs(json.loads(resp.read()), repo_name)
        except Exception as e:
            logger.debug(f"GitLab MR fetch (created) for {repo_name}: {e}")

        url_open = (
            f"https://{gitlab_host}/api/v4/projects/{encoded}/merge_requests"
            f"?scope=all&author_username={username}"
            f"&state=opened&per_page=100"
        )
        req = urllib.request.Request(url_open, headers={"PRIVATE-TOKEN": token})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                _add_mrs(json.loads(resp.read()), repo_name)
        except Exception as e:
            logger.debug(f"GitLab MR fetch (open) for {repo_name}: {e}")

        # MRs merged during the quarter regardless of creation date
        url_merged = (
            f"https://{gitlab_host}/api/v4/projects/{encoded}/merge_requests"
            f"?scope=all&author_username={username}"
            f"&state=merged&updated_after={q_start}&updated_before={q_end}&per_page=100"
        )
        req = urllib.request.Request(url_merged, headers={"PRIVATE-TOKEN": token})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                _add_mrs(json.loads(resp.read()), repo_name)
        except Exception as e:
            logger.debug(f"GitLab MR fetch (merged) for {repo_name}: {e}")

    logger.info(f"Loaded {len(all_mrs)} GitLab MRs for Q{quarter} {year}")
    return all_mrs


def build_strategy_alignment(  # noqa: C901
    year: int,
    quarter: int,
    cumulative_points: dict[str, int],
    perf_dir: Path,
    emails_dir: Path,
) -> dict:
    """Aggregate executive email data into a strategy alignment structure.

    Loads all cached executive emails for the quarter and maps them to the
    user's issue hierarchy and competency pillars.
    """
    if not emails_dir.exists():
        return {"emails_loaded": 0, "priorities": [], "coverage_summary": {}}

    all_priorities: dict[str, dict] = {}
    all_themes: list[dict] = []
    email_count = 0
    senders_seen: set[str] = set()
    all_issue_keys: dict[str, list[str]] = {}

    for f in sorted(emails_dir.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        email_count += 1
        senders_seen.add(data.get("sender_email", data.get("sender", "unknown")))

        for prio in data.get("priorities", []):
            name = prio.get("name", "")
            if not name:
                continue
            key = name.lower()
            if key not in all_priorities:
                all_priorities[key] = {
                    "name": name,
                    "context": prio.get("context", ""),
                    "issue_keys": list(prio.get("issue_keys", [])),
                    "email_ids": [data.get("email_id", "")],
                    "senders": [data.get("sender_email", "")],
                }
            else:
                existing = all_priorities[key]
                for ik in prio.get("issue_keys", []):
                    if ik not in existing["issue_keys"]:
                        existing["issue_keys"].append(ik)
                eid = data.get("email_id", "")
                if eid and eid not in existing["email_ids"]:
                    existing["email_ids"].append(eid)
                s = data.get("sender_email", "")
                if s and s not in existing["senders"]:
                    existing["senders"].append(s)

        for ik, contexts in data.get("issue_keys", {}).items():
            if ik not in all_issue_keys:
                all_issue_keys[ik] = []
            for ctx in contexts:
                if ctx not in all_issue_keys[ik]:
                    all_issue_keys[ik].append(ctx)

        for theme in data.get("themes", []):
            all_themes.append(theme)

    if not email_count:
        return {"emails_loaded": 0, "priorities": [], "coverage_summary": {}}

    cache_file = perf_dir / "jira_hierarchy_cache.json"
    user_issues: dict[str, dict] = {}
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as fh:
                user_issues = json.load(fh).get("issues", {})
        except Exception:
            pass

    try:
        user_issues = enrich_user_issues_from_jira(year, quarter, user_issues)
    except Exception as e:
        logger.warning(f"Failed to enrich from Jira API: {e}")

    gitlab_mrs: list[dict] = []
    try:
        gitlab_mrs = get_quarter_gitlab_mrs(year, quarter)
    except Exception as e:
        logger.warning(f"Failed to load GitLab MRs: {e}")

    anstrat_to_user_issues: dict[str, list[str]] = {}
    for ukey, uinfo in user_issues.items():
        if ukey.startswith("ANSTRAT-"):
            continue
        pi = uinfo.get("parent_initiative", "")
        if pi and pi.startswith("ANSTRAT-"):
            anstrat_to_user_issues.setdefault(pi, []).append(ukey)
        epic_key = uinfo.get("epic", "")
        if epic_key and epic_key in user_issues:
            epic_pi = user_issues[epic_key].get("parent_initiative", "")
            if epic_pi and epic_pi.startswith("ANSTRAT-"):
                anstrat_to_user_issues.setdefault(epic_pi, []).append(ukey)

    pillar_keywords = {
        "Technical Contribution": [
            "python",
            "django",
            "build",
            "pipeline",
            "ci/cd",
            "konflux",
            "security",
            "cve",
            "cra",
            "dast",
            "openapi",
            "spec",
            "infrastructure",
            "operator",
            "sre",
            "test",
            "quality",
            "upgrade",
            "tech",
            "code",
            "api",
            "redis",
            "migration",
            "innovation",
            "poc",
            "prototype",
        ],
        "Leadership": [
            "leadership",
            "team",
            "peer",
            "collaborate",
            "recognition",
            "community",
            "present",
            "speak",
            "blog",
            "portfolio",
            "cross-team",
            "cross-functional",
            "strategy",
            "process",
            "improvement",
        ],
        "Mentorship": [
            "mentor",
            "onboard",
            "hiring",
            "associate",
            "intern",
            "coach",
            "training",
            "knowledge share",
            "teach",
            "newcomer",
            "growth",
        ],
        "End-to-End Delivery": [
            "deliver",
            "release",
            "deploy",
            "ship",
            "milestone",
            "okr",
            "objective",
            "initiative",
            "anstrat",
            "roadmap",
            "feature",
            "epic",
            "sprint",
            "backlog",
            "plan",
            "customer",
            "partner",
            "cisco",
            "telstra",
            "azure",
            "f2f",
            "kudos",
            "ai",
            "llm",
            "lightspeed",
            "alia",
            "machine learning",
        ],
    }

    priorities_out: list[dict] = []
    covered_count = 0
    for prio_data in all_priorities.values():
        name = prio_data["name"]
        prio_keys = set(prio_data.get("issue_keys", []))
        matched_user_issues = [k for k in prio_keys if k in user_issues]

        for ik in list(prio_keys):
            if ik.startswith("ANSTRAT-"):
                for ukey in anstrat_to_user_issues.get(ik, []):
                    if ukey not in matched_user_issues:
                        matched_user_issues.append(ukey)

        matched_mrs: list[str] = []
        for mr in gitlab_mrs:
            mr_title = mr.get("title", "")
            for ik in prio_keys:
                if ik in mr_title:
                    label = f"!{mr['iid']} ({mr['project']})"
                    if label not in matched_mrs:
                        matched_mrs.append(label)

        prio_text = f"{name} {prio_data.get('context', '')}".lower()
        prio_phrases = set(
            re.findall(
                r"(?:python|django|ansible|ubi|rhel|openshift)\s*\d[\d.]*", prio_text
            )
        )
        prio_phrases.update(re.findall(r"\b[a-z]+[\s-]\d+\.\d+\b", prio_text))

        stop_words = {
            "the",
            "and",
            "for",
            "are",
            "with",
            "this",
            "that",
            "from",
            "not",
            "has",
            "was",
            "will",
            "can",
            "all",
            "been",
            "have",
            "into",
            "new",
            "use",
            "its",
            "may",
        }
        prio_words = {
            w for w in re.findall(r"[a-z]{3,}", prio_text) if w not in stop_words
        }

        def _text_matches(
            text: str,
            _prio_phrases=prio_phrases,
            _prio_words=prio_words,
        ) -> bool:
            text_lower = text.lower()
            for phrase in _prio_phrases:
                normalized = re.sub(r"\s+", " ", phrase).strip()
                if normalized in text_lower:
                    return True
            text_words = set(re.findall(r"[a-z]{3,}", text_lower))
            return len(_prio_words & text_words) >= 3

        if not matched_user_issues:
            for ukey, uinfo in user_issues.items():
                if ukey.startswith("ANSTRAT-"):
                    continue
                usummary = uinfo.get("summary", "")
                if usummary and _text_matches(usummary):
                    if ukey not in matched_user_issues:
                        matched_user_issues.append(ukey)

        if not matched_mrs:
            for mr in gitlab_mrs:
                mr_text = f"{mr.get('title', '')} {mr.get('description', '')}"
                if _text_matches(mr_text):
                    label = f"!{mr['iid']} ({mr['project']})"
                    if label not in matched_mrs:
                        matched_mrs.append(label)

        status = "covered" if (matched_user_issues or matched_mrs) else "gap"
        if status == "covered":
            covered_count += 1

        name_lower = name.lower()
        context_lower = prio_data.get("context", "").lower()
        combined = f"{name_lower} {context_lower}"
        pillar = "End-to-End Delivery"
        best_score = 0
        for pname, kws in pillar_keywords.items():
            score = sum(1 for kw in kws if kw in combined)
            if score > best_score:
                best_score = score
                pillar = pname

        priorities_out.append(
            {
                "name": name,
                "context": prio_data.get("context", "")[:200],
                "status": status,
                "pillar": pillar,
                "issue_keys": list(prio_keys),
                "matched_user_issues": matched_user_issues[:10],
                "matched_mrs": matched_mrs[:10],
                "senders": prio_data.get("senders", []),
            }
        )

    total_p = len(priorities_out)
    coverage_pct = round(covered_count / max(total_p, 1) * 100)

    seen_themes: dict[str, dict] = {}
    for t in all_themes:
        tn = t.get("name", "")
        if tn not in seen_themes:
            seen_themes[tn] = t
        else:
            existing = seen_themes[tn]
            existing["strength"] = max(
                existing.get("strength", 0), t.get("strength", 0)
            )

    pillar_summary: dict[str, dict] = {}
    for pname in [
        "Technical Contribution",
        "Leadership",
        "Mentorship",
        "End-to-End Delivery",
    ]:
        cat_points = sum(
            v
            for cid, v in cumulative_points.items()
            if COMPETENCY_DEFS.get(cid, {}).get("category", "") == pname
        )
        prio_count = sum(1 for p in priorities_out if p["pillar"] == pname)
        covered = sum(
            1
            for p in priorities_out
            if p["pillar"] == pname and p["status"] == "covered"
        )
        pillar_summary[pname] = {
            "competency_points": cat_points,
            "priority_count": prio_count,
            "covered": covered,
            "gaps": prio_count - covered,
        }

    jira_count = sum(1 for k in user_issues if not k.startswith("ANSTRAT-"))

    return {
        "emails_loaded": email_count,
        "senders": list(senders_seen),
        "priorities": priorities_out,
        "themes": list(seen_themes.values()),
        "all_issue_keys": {k: v[:3] for k, v in all_issue_keys.items()},
        "pillar_summary": pillar_summary,
        "coverage_summary": {
            "total_priorities": total_p,
            "covered": covered_count,
            "gaps": total_p - covered_count,
            "coverage_pct": coverage_pct,
        },
        "user_work_summary": {
            "jira_issues": jira_count,
            "gitlab_mrs": len(gitlab_mrs),
        },
    }
