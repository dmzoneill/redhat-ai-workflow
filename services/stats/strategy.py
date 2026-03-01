"""ANSTRAT strategy alignment analysis — maps organizational priorities to individual contributions."""

import json
import logging
import os
import re
import subprocess
import urllib.error
from datetime import timedelta
from pathlib import Path

import yaml

from server.utils import run_cmd_sync
from services.stats.collector_utils import STOP_WORDS, rate_limited_api_call
from services.stats.quarter_utils import get_quarter_end, get_quarter_start
from services.stats.scorer import COMPETENCY_DEFS

logger = logging.getLogger(__name__)

PRIORITY_CONTEXT_TRUNCATE = 300
TEXT_OVERLAP_THRESHOLD = 0.25
CATALOG_BRIDGE_OVERLAP_THRESHOLD = 0.20
MIN_OVERLAP_WORDS_EMAIL = 5
MIN_OVERLAP_WORDS_GDRIVE = 4
MIN_OVERLAP_WORDS_MATCH = 4
QUARTER_WEEKDAYS = 65
INFERRED_CACHE_AGE_FALLBACK_HOURS = 999
INFERRED_CACHE_FRESH_HOURS = 24

_EMAIL_DISPLAY_NAMES: dict[str, str] = {
    "sharwell@redhat.com": "Scott Harwell",
    "jhardy@redhat.com": "John Hardy",
    "dmendoza@redhat.com": "Dafne Mendoza",
}


def _email_to_display(email: str) -> str:
    """Convert email to human-readable display name."""
    if email in _EMAIL_DISPLAY_NAMES:
        return _EMAIL_DISPLAY_NAMES[email]
    local = email.split("@")[0] if "@" in email else email
    return local.replace(".", " ").replace("-", " ").title()


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
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read executive email %s: %s", f.name, e)
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
                    "context": prio.get("context", "")[:PRIORITY_CONTEXT_TRUNCATE],
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
    min_overlap_words: int = MIN_OVERLAP_WORDS_MATCH,
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
        kw_set = prio.get("text_keywords", set())
        overlap = len(text_words & kw_set)
        if overlap < min_overlap_words:
            continue
        smaller = min(len(text_words), len(kw_set)) or 1
        if overlap / smaller >= TEXT_OVERLAP_THRESHOLD:
            if prio["name"] not in matched_names:
                matched_names.append(prio["name"])

    return bool(matched_names), matched_names


def enrich_user_issues_from_jira(
    year: int, quarter: int, user_issues: dict[str, dict]
) -> dict[str, dict]:
    """Query Jira API for ALL user issues in the quarter (any status).

    Merges results into user_issues dict so strategy alignment has full data.
    """
    q_start = get_quarter_start(year, quarter).isoformat()
    q_end = (get_quarter_end(year, quarter) + timedelta(days=1)).isoformat()

    jql = (
        f"assignee = currentUser() AND "
        f'(updatedDate >= "{q_start}" OR createdDate >= "{q_start}") '
        f'AND createdDate <= "{q_end}" '
        f"ORDER BY updated DESC"
    )

    added = 0
    try:
        ok, output = run_cmd_sync(
            ["rh-issue", "search", jql, "--max-results", "100"],
            timeout=60,
        )
        if ok:
            for line in output.splitlines():
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
        else:
            logger.warning(f"Jira API query failed: {output}")
    except (subprocess.TimeoutExpired, OSError) as e:
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
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to load config.json for GitLab MR query: %s", e)
        return []

    gitlab_host = cfg.get("gitlab", {}).get("host", "gitlab.cee.redhat.com")

    token = os.environ.get("GITLAB_TOKEN", "")
    if not token:
        glab_config = Path.home() / ".config" / "glab-cli" / "config.yml"
        if glab_config.exists():
            try:
                with open(glab_config, encoding="utf-8") as fh:
                    gc = yaml.safe_load(fh)
                for host_data in gc.get("hosts", {}).values():
                    token = host_data.get("token", "")
                    if token:
                        break
            except (OSError, yaml.YAMLError) as e:
                logger.warning("Failed to read GitLab token from glab config: %s", e)
    if not token:
        logger.warning("No GitLab token found for MR enrichment")
        return []

    username = ""
    try:
        user_url = f"https://{gitlab_host}/api/v4/user"
        user_req = urllib.request.Request(user_url, headers={"PRIVATE-TOKEN": token})

        def _fetch_user() -> dict:
            with urllib.request.urlopen(user_req, timeout=10) as resp:
                return json.loads(resp.read())

        user_data = rate_limited_api_call(
            _fetch_user, min_interval=0.5, max_retries=3, base_delay=1.0
        )
        username = user_data.get("username", "")
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        logger.warning("GitLab /api/v4/user failed: %s", e)
    if not username:
        logger.warning("Could not determine GitLab username")
        return []

    q_start = get_quarter_start(year, quarter).isoformat() + "T00:00:00Z"
    q_end = (
        get_quarter_end(year, quarter) + timedelta(days=1)
    ).isoformat() + "T00:00:00Z"

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

            def _fetch_mrs(_req=req) -> list:
                with urllib.request.urlopen(_req, timeout=15) as resp:
                    return json.loads(resp.read())

            mrs_list = rate_limited_api_call(
                _fetch_mrs, min_interval=0.5, max_retries=3, base_delay=1.0
            )
            _add_mrs(mrs_list, repo_name)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            logger.warning("GitLab MR fetch (created) for %s: %s", repo_name, e)

        url_open = (
            f"https://{gitlab_host}/api/v4/projects/{encoded}/merge_requests"
            f"?scope=all&author_username={username}"
            f"&state=opened&per_page=100"
        )
        req = urllib.request.Request(url_open, headers={"PRIVATE-TOKEN": token})
        try:

            def _fetch_mrs_open(_req=req) -> list:
                with urllib.request.urlopen(_req, timeout=15) as resp:
                    return json.loads(resp.read())

            mrs_list = rate_limited_api_call(
                _fetch_mrs_open, min_interval=0.5, max_retries=3, base_delay=1.0
            )
            _add_mrs(mrs_list, repo_name)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            logger.warning("GitLab MR fetch (open) for %s: %s", repo_name, e)

        url_merged = (
            f"https://{gitlab_host}/api/v4/projects/{encoded}/merge_requests"
            f"?scope=all&author_username={username}"
            f"&state=merged&updated_after={q_start}&updated_before={q_end}&per_page=100"
        )
        req = urllib.request.Request(url_merged, headers={"PRIVATE-TOKEN": token})
        try:

            def _fetch_mrs_merged(_req=req) -> list:
                with urllib.request.urlopen(_req, timeout=15) as resp:
                    return json.loads(resp.read())

            mrs_list = rate_limited_api_call(
                _fetch_mrs_merged, min_interval=0.5, max_retries=3, base_delay=1.0
            )
            _add_mrs(mrs_list, repo_name)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            logger.warning("GitLab MR fetch (merged) for %s: %s", repo_name, e)

    logger.info(f"Loaded {len(all_mrs)} GitLab MRs for Q{quarter} {year}")
    return all_mrs


def build_sender_relationships(  # noqa: C901
    emails_dir: Path,
    ownership: dict,
    jira_activity: dict | None = None,
    gdrive_docs: dict | None = None,
) -> dict:
    """Discover strategic ownership passively from multiple data sources.

    Ownership is inferred from passive signals -- NOT from the Jira assignee
    field (which shows who does the engineering work).  Passive signals:
    - Emails: issue key mentions, theme overlap
    - Jira reporter: who filed the issue (= who cares about it strategically)
    - Google Drive: doc authorship and content on related topics

    Returns a structure of relationships and per-sender summaries.
    """
    issues_map = ownership.get("issues", {})
    if not issues_map:
        return {"relationships": [], "sender_summaries": {}, "data_sources": {}}

    relationships: list[dict] = []
    sender_stats: dict[str, dict] = {}
    seen_pairs: set[tuple[str, str]] = set()
    data_sources: dict[str, int] = {"emails": 0, "jira_activity": 0, "gdrive": 0}

    # --- Source 1: Executive emails (existing logic) ---
    if emails_dir.exists():
        for f in sorted(emails_dir.glob("*.json"), key=lambda p: p.stat().st_mtime):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Failed to read email file %s: %s", f.name, e)
                continue

            sender = data.get("sender_email", data.get("sender", "")).lower()
            if not sender:
                continue

            if sender not in sender_stats:
                sender_stats[sender] = {
                    "total_emails": 0,
                    "jira_issues": 0,
                    "gdrive_docs": 0,
                    "anstrat_count": 0,
                    "top_themes": [],
                    "coverage": 0.0,
                }
            sender_stats[sender]["total_emails"] += 1
            data_sources["emails"] += 1

            email_issue_keys: set[str] = set()
            for ik_list in data.get("issue_keys", {}).keys():
                email_issue_keys.add(ik_list)
            for prio in data.get("priorities", []):
                for ik in prio.get("issue_keys", []):
                    email_issue_keys.add(ik)

            email_text = json.dumps(data.get("priorities", []) + data.get("themes", []))
            email_words = {
                w
                for w in re.findall(r"[a-z]{3,}", email_text.lower())
                if w not in STOP_WORDS
            }

            email_date = data.get("date", "")

            for anstrat_key, issue_info in issues_map.items():
                pair = (sender, anstrat_key)
                if pair in seen_pairs:
                    continue

                match_types: list[str] = []
                evidence: list[str] = []
                confidence = 0.0

                if anstrat_key in email_issue_keys:
                    match_types.append("email_ref")
                    evidence.append(f"Email {email_date}: mentioned {anstrat_key}")
                    confidence = max(confidence, 0.95)

                if not match_types:
                    summary_words = {
                        w
                        for w in re.findall(
                            r"[a-z]{3,}", issue_info.get("summary", "").lower()
                        )
                        if w not in STOP_WORDS
                    }
                    overlap = len(email_words & summary_words)
                    smaller = min(len(email_words), len(summary_words)) or 1
                    if (
                        overlap >= MIN_OVERLAP_WORDS_EMAIL
                        and overlap / smaller >= TEXT_OVERLAP_THRESHOLD
                    ):
                        match_types.append("theme")
                        evidence.append(
                            f"Theme overlap ({overlap} words) with: "
                            f"{issue_info.get('summary', '')[:60]}"
                        )
                        confidence = max(confidence, min(0.5 + overlap * 0.05, 0.85))

                if match_types:
                    seen_pairs.add(pair)
                    relationships.append(
                        {
                            "sender": sender,
                            "anstrat_key": anstrat_key,
                            "match_types": match_types,
                            "evidence": evidence,
                            "confidence": round(confidence, 2),
                        }
                    )

    # --- Source 2: Jira passive signals (reporter/creator, NOT assignee) ---
    if jira_activity:
        for email, act in jira_activity.get("sender_activity", {}).items():
            sender = email.lower()
            if sender not in sender_stats:
                sender_stats[sender] = {
                    "total_emails": 0,
                    "jira_issues": 0,
                    "gdrive_docs": 0,
                    "anstrat_count": 0,
                    "top_themes": [],
                    "coverage": 0.0,
                }

            sender_issues = act.get("issues", [])
            sender_stats[sender]["jira_issues"] = len(sender_issues)
            data_sources["jira_activity"] += len(sender_issues)

            jira_issue_keys = {i["key"] for i in sender_issues}
            jira_themes = {t.lower() for t in act.get("themes", [])}

            for anstrat_key, issue_info in issues_map.items():
                pair = (sender, anstrat_key)
                if pair in seen_pairs:
                    continue

                match_types: list[str] = []
                evidence: list[str] = []
                confidence = 0.0

                if anstrat_key in jira_issue_keys:
                    match_types.append("jira_reporter")
                    evidence.append(f"Filed/reported {anstrat_key} in Jira")
                    confidence = max(confidence, 0.95)

                if not match_types:
                    summary_words = {
                        w
                        for w in re.findall(
                            r"[a-z]{3,}", issue_info.get("summary", "").lower()
                        )
                        if w not in STOP_WORDS
                    }
                    theme_overlap = len(jira_themes & summary_words)
                    if theme_overlap >= 2:
                        match_types.append("jira_theme")
                        evidence.append(
                            f"Jira reporter activity theme overlap ({theme_overlap} words) "
                            f"with: {issue_info.get('summary', '')[:60]}"
                        )
                        confidence = max(
                            confidence, min(0.4 + theme_overlap * 0.08, 0.80)
                        )

                if match_types:
                    seen_pairs.add(pair)
                    relationships.append(
                        {
                            "sender": sender,
                            "anstrat_key": anstrat_key,
                            "match_types": match_types,
                            "evidence": evidence,
                            "confidence": round(confidence, 2),
                        }
                    )

    # --- Source 3: Google Drive documents ---
    if gdrive_docs:
        docs = gdrive_docs.get("documents", [])
        data_sources["gdrive"] = len(docs)

        for doc in docs:
            related = doc.get("related_senders", [])
            doc_name = doc.get("name", "")
            doc_name_lower = doc_name.lower()
            doc_words = {
                w
                for w in re.findall(r"[a-z]{3,}", doc_name_lower)
                if w not in STOP_WORDS
            }

            anstrat_refs = re.findall(r"ANSTRAT-\d+", doc_name)

            for sender in related:
                sender = sender.lower()
                if sender not in sender_stats:
                    sender_stats[sender] = {
                        "total_emails": 0,
                        "jira_issues": 0,
                        "gdrive_docs": 0,
                        "anstrat_count": 0,
                        "top_themes": [],
                        "coverage": 0.0,
                    }
                sender_stats[sender]["gdrive_docs"] = (
                    sender_stats[sender].get("gdrive_docs", 0) + 1
                )

                for ref in anstrat_refs:
                    pair = (sender, ref)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    relationships.append(
                        {
                            "sender": sender,
                            "anstrat_key": ref,
                            "match_types": ["gdrive_ref"],
                            "evidence": [
                                f"Google Doc '{doc_name[:60]}' references {ref}"
                            ],
                            "confidence": 0.90,
                        }
                    )

                for anstrat_key, issue_info in issues_map.items():
                    pair = (sender, anstrat_key)
                    if pair in seen_pairs:
                        continue
                    summary_words = {
                        w
                        for w in re.findall(
                            r"[a-z]{3,}", issue_info.get("summary", "").lower()
                        )
                        if w not in STOP_WORDS
                    }
                    overlap = len(doc_words & summary_words)
                    smaller = min(len(doc_words), len(summary_words)) or 1
                    if (
                        overlap >= MIN_OVERLAP_WORDS_GDRIVE
                        and overlap / smaller >= TEXT_OVERLAP_THRESHOLD
                    ):
                        seen_pairs.add(pair)
                        relationships.append(
                            {
                                "sender": sender,
                                "anstrat_key": anstrat_key,
                                "match_types": ["gdrive_theme"],
                                "evidence": [
                                    f"Google Doc '{doc_name[:50]}' theme overlap "
                                    f"({overlap} words) with {anstrat_key}"
                                ],
                                "confidence": round(min(0.4 + overlap * 0.06, 0.75), 2),
                            }
                        )

    # --- Compute summaries ---
    for sender, stats in sender_stats.items():
        related_anstrats = {
            r["anstrat_key"] for r in relationships if r["sender"] == sender
        }
        stats["anstrat_count"] = len(related_anstrats)

        all_themes: list[str] = []
        for ak in related_anstrats:
            info = issues_map.get(ak, {})
            for w in re.findall(r"[A-Za-z]{3,}", info.get("summary", "")):
                low = w.lower()
                if low not in STOP_WORDS and low not in all_themes:
                    all_themes.append(low)
        stats["top_themes"] = all_themes[:8]

        total_anstrat = len(issues_map)
        if total_anstrat > 0:
            stats["coverage"] = round(len(related_anstrats) / total_anstrat, 2)

    return {
        "relationships": relationships,
        "sender_summaries": sender_stats,
        "data_sources": data_sources,
    }


def infer_relationships_with_llm(
    emails_dir: Path,
    ownership: dict,
    hierarchy_cache: dict,
) -> list[dict]:
    """Use LLM to discover non-obvious email-to-ANSTRAT connections.

    Builds a prompt from email summaries, ANSTRAT issues, and the user's
    current work items, then asks the LLM to identify alignments.
    Results are cached to avoid repeated inference.
    """
    cache_dir = emails_dir.parent if emails_dir.exists() else emails_dir
    cache_file = cache_dir / "inferred_relationships.json"
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as fh:
                cached = json.load(fh)
            age_hours = 0
            if cached.get("inferred_at"):
                from datetime import datetime as _dt

                try:
                    inferred_dt = _dt.fromisoformat(cached["inferred_at"])
                    age_hours = (_dt.now() - inferred_dt).total_seconds() / 3600
                except (ValueError, TypeError) as e:
                    logger.warning("Failed to parse inferred_at timestamp: %s", e)
                    age_hours = INFERRED_CACHE_AGE_FALLBACK_HOURS
            if age_hours < INFERRED_CACHE_FRESH_HOURS:
                return cached.get("relationships", [])
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read inferred relationships cache: %s", e)

    email_summaries: list[str] = []
    if emails_dir.exists():
        for f in sorted(emails_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)[
            -20:
        ]:
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
                sender = data.get("sender_email", "unknown")
                prios = [p.get("name", "") for p in data.get("priorities", [])]
                if prios:
                    email_summaries.append(f"From {sender}: {', '.join(prios[:5])}")
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Failed to read email file for inference: %s", e)
                continue

    issues_map = ownership.get("issues", {})
    anstrat_lines: list[str] = []
    for key, info in list(issues_map.items())[:50]:
        anstrat_lines.append(
            f"{key}: {info.get('summary', '')} [{info.get('type', '')}, {info.get('status', '')}]"
        )

    user_issues: list[str] = []
    for key, info in list(hierarchy_cache.get("issues", {}).items())[:30]:
        if not key.startswith("ANSTRAT-"):
            user_issues.append(f"{key}: {info.get('summary', '')}")

    if not email_summaries or not anstrat_lines:
        return []

    prompt = (
        "Given these executive email priorities and ANSTRAT engineering initiatives, "
        "identify non-obvious connections between emails and ANSTRAT issues. "
        "Return ONLY a JSON array of objects with: sender, anstrat_key, reasoning, confidence (0-1).\n\n"
        "EMAIL PRIORITIES:\n" + "\n".join(email_summaries) + "\n\n"
        "ANSTRAT INITIATIVES:\n" + "\n".join(anstrat_lines) + "\n\n"
    )
    if user_issues:
        prompt += "USER WORK ITEMS:\n" + "\n".join(user_issues[:15]) + "\n\n"
    prompt += "Return the JSON array only, no markdown fences."

    try:
        result = subprocess.run(
            ["python3", "-c", _LLM_INFERENCE_SCRIPT],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "LLM_PROMPT": prompt},
        )
        if result.returncode == 0 and result.stdout.strip():
            raw = result.stdout.strip()
            if raw.startswith("```"):
                raw = re.sub(r"```\w*\n?", "", raw).strip()
            inferred = json.loads(raw)
            if isinstance(inferred, list):
                output = {
                    "relationships": inferred[:20],
                    "inferred_at": __import__("datetime").datetime.now().isoformat(),
                }
                cache_dir.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as fh:
                    json.dump(output, fh, indent=2)
                return inferred[:20]
    except subprocess.TimeoutExpired:
        logger.warning("LLM inference timed out")
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as e:
        logger.warning(f"LLM inference failed: {e}")

    return []


_LLM_INFERENCE_SCRIPT = """\
import sys, os, json
prompt = os.environ.get("LLM_PROMPT", sys.stdin.read())
try:
    from openai import OpenAI
    client = OpenAI()
    resp = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000,
    )
    print(resp.choices[0].message.content)
except Exception as e:
    print(json.dumps([]), end="")
"""


def build_strategy_alignment(  # noqa: C901
    year: int,
    quarter: int,
    cumulative_points: dict[str, int],
    perf_dir: Path,
    emails_dir: Path,
    ownership: dict | None = None,
    jira_activity: dict | None = None,
    gdrive_docs: dict | None = None,
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
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "Failed to read email file %s for strategy alignment: %s", f.name, e
            )
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

    # --- ANSTRAT catalog bridging ---
    # Match exec priorities to ANSTRAT catalog entries by text/theme similarity
    # so that priorities without explicit issue_keys still link to ANSTRATs.
    catalog_file = perf_dir / "anstrat_catalog.json"
    if catalog_file.exists():
        try:
            with open(catalog_file, encoding="utf-8") as fh:
                catalog_data = json.load(fh)
            catalog_issues = catalog_data.get("issues", {})
            for prio_data in all_priorities.values():
                prio_text = (
                    f"{prio_data['name']} {prio_data.get('context', '')}"
                ).lower()
                prio_words = {
                    w
                    for w in re.findall(r"[a-z]{3,}", prio_text)
                    if w not in STOP_WORDS
                }
                prio_phrases = set(
                    re.findall(
                        r"(?:python|django|ansible|aap|ubi|rhel|openshift)"
                        r"\s*\d[\d.]*",
                        prio_text,
                    )
                )
                for akey, ainfo in catalog_issues.items():
                    if akey in prio_data["issue_keys"]:
                        continue
                    a_text = (
                        f"{ainfo.get('summary', '')} "
                        f"{' '.join(ainfo.get('themes', []))}"
                    ).lower()
                    for phrase in prio_phrases:
                        if re.sub(r"\s+", " ", phrase).strip() in a_text:
                            prio_data["issue_keys"].append(akey)
                            break
                    else:
                        a_words = {
                            w
                            for w in re.findall(r"[a-z]{3,}", a_text)
                            if w not in STOP_WORDS
                        }
                        overlap = len(prio_words & a_words)
                        smaller = min(len(prio_words), len(a_words)) or 1
                        if (
                            overlap >= MIN_OVERLAP_WORDS_EMAIL
                            and overlap / smaller >= CATALOG_BRIDGE_OVERLAP_THRESHOLD
                        ):
                            prio_data["issue_keys"].append(akey)
            bridged = sum(
                1
                for p in all_priorities.values()
                if any(k.startswith("ANSTRAT-") for k in p["issue_keys"])
            )
            logger.info(
                "ANSTRAT catalog bridge: %d/%d priorities linked to ANSTRATs",
                bridged,
                len(all_priorities),
            )
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to load ANSTRAT catalog for bridging: %s", e)

    cache_file = perf_dir / "jira_hierarchy_cache.json"
    user_issues: dict[str, dict] = {}
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as fh:
                user_issues = json.load(fh).get("issues", {})
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to load Jira hierarchy cache %s: %s", cache_file, e)

    try:
        user_issues = enrich_user_issues_from_jira(year, quarter, user_issues)
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning(f"Failed to enrich from Jira API: {e}")

    gitlab_mrs: list[dict] = []
    try:
        gitlab_mrs = get_quarter_gitlab_mrs(year, quarter)
    except (OSError, json.JSONDecodeError, urllib.error.URLError) as e:
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

    # --- Discover user issues under priority-linked ANSTRATs ---
    # enrich_user_issues_from_jira doesn't populate parent_initiative,
    # so anstrat_to_user_issues may be empty. Query Jira for child issues
    # under ANSTRATs that are linked to exec priorities.
    linked_anstrats = set()
    for prio_data in all_priorities.values():
        for ik in prio_data.get("issue_keys", []):
            if ik.startswith("ANSTRAT-"):
                linked_anstrats.add(ik)
    unfilled = linked_anstrats - set(anstrat_to_user_issues.keys())
    if unfilled:
        for anstrat_key in unfilled:
            jql = (
                f'"Parent Link" = {anstrat_key} '
                f"AND assignee = currentUser() "
                f"ORDER BY updated DESC"
            )
            try:
                ok, output = run_cmd_sync(
                    ["rh-issue", "search", jql, "--max-results", "50"],
                    timeout=30,
                    env={"COLUMNS": "500"},
                )
                if ok:
                    for line in output.splitlines():
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 5 and parts[0].startswith(
                            ("AAP-", "ANSTRAT-")
                        ):
                            child_key = parts[0]
                            anstrat_to_user_issues.setdefault(anstrat_key, []).append(
                                child_key
                            )
                            if child_key not in user_issues:
                                user_issues[child_key] = {
                                    "key": child_key,
                                    "summary": (parts[4] if len(parts) > 4 else ""),
                                    "status": (parts[2] if len(parts) > 2 else ""),
                                    "issue_type": (parts[1] if len(parts) > 1 else ""),
                                    "parent_initiative": anstrat_key,
                                    "source": "anstrat_child_query",
                                }
            except (subprocess.TimeoutExpired, OSError) as e:
                logger.warning("Failed to query children of %s: %s", anstrat_key, e)
        discovered = sum(len(v) for v in anstrat_to_user_issues.values())
        if discovered:
            logger.info(
                "ANSTRAT child discovery: %d user issues under %d ANSTRATs",
                discovered,
                len([k for k, v in anstrat_to_user_issues.items() if v]),
            )

    # User-assigned ANSTRATs count as direct coverage
    user_anstrats = {k for k in user_issues if k.startswith("ANSTRAT-")}

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

        # ANSTRAT cascade: if priority links to an ANSTRAT, pull in child issues
        for ik in list(prio_keys):
            if ik.startswith("ANSTRAT-"):
                if ik in user_anstrats and ik not in matched_user_issues:
                    matched_user_issues.append(ik)
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
                r"(?:python|django|ansible|aap|ubi|rhel|openshift)\s*\d[\d.]*",
                prio_text,
            )
        )
        prio_phrases.update(re.findall(r"\b[a-z]{3,}-\d+\.\d+\b", prio_text))

        prio_words = {
            w for w in re.findall(r"[a-z]{3,}", prio_text) if w not in STOP_WORDS
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
            text_words = {
                w for w in re.findall(r"[a-z]{3,}", text_lower) if w not in STOP_WORDS
            }
            overlap = len(_prio_words & text_words)
            if overlap < MIN_OVERLAP_WORDS_MATCH:
                return False
            smaller = min(len(_prio_words), len(text_words)) or 1
            return overlap / smaller >= TEXT_OVERLAP_THRESHOLD

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

    sender_rel: dict = {"relationships": [], "sender_summaries": {}, "data_sources": {}}
    if ownership and ownership.get("issues"):
        sender_rel = build_sender_relationships(
            emails_dir,
            ownership,
            jira_activity=jira_activity,
            gdrive_docs=gdrive_docs,
        )

        _sender_summaries = sender_rel.get("sender_summaries", {})  # noqa: F841
        for prio_out in priorities_out:
            prio_senders = prio_out.get("senders", [])
            prio_keys = set(prio_out.get("issue_keys", []))
            for rel in sender_rel.get("relationships", []):
                if rel["anstrat_key"] in prio_keys:
                    s = rel["sender"]
                    if s not in prio_senders:
                        prio_senders.append(s)
            prio_out["sender_names"] = [_email_to_display(s) for s in prio_senders]

    jira_activity_summary: dict = {}
    if jira_activity:
        for email, act in jira_activity.get("sender_activity", {}).items():
            jira_activity_summary[email] = {
                "issue_count": act.get("issue_count", 0),
                "projects": act.get("projects", []),
                "themes": act.get("themes", [])[:8],
            }

    gdrive_summary: dict = {}
    if gdrive_docs:
        docs = gdrive_docs.get("documents", [])
        gdrive_summary = {
            "total_docs": len(docs),
            "direct_docs": sum(1 for d in docs if d.get("relevance") == "direct"),
            "keyword_docs": sum(1 for d in docs if d.get("relevance") == "keyword"),
        }

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
        "sender_relationships": sender_rel,
        "anstrat_catalog_count": len((ownership or {}).get("issues", {})),
        "jira_activity_summary": jira_activity_summary,
        "gdrive_summary": gdrive_summary,
    }
