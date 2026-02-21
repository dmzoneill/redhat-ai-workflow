import json
import logging
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from server.paths import AA_CONFIG_DIR, PERFORMANCE_DIR
from services.stats.email_parser import collect_executive_emails_for_date
from services.stats.scorer import (
    get_effective_defs,
    get_merged_config,
    get_session_integration_config,
    get_strategy_alignment_config,
    map_competencies_with_signals,
)
from services.stats.strategy import match_event_to_strategy

logger = logging.getLogger(__name__)


def _detect_scope(item_id: str, hierarchy_cache: dict) -> str:
    """Determine work item scope from Jira hierarchy data."""
    if item_id.startswith("ANSTRAT-"):
        return "anstrat"

    info = hierarchy_cache.get("issues", {}).get(item_id, {})
    issue_type = info.get("issue_type", "").lower()

    if "epic" in issue_type:
        return "epic"
    if any(t in issue_type for t in ("story", "task", "bug", "sub-task", "subtask")):
        return "story"
    return "story"


def _detect_role(
    item_id: str,
    source: str,
    event_type: str,
    hierarchy_cache: dict,
    current_user: str,
    current_email: str,
) -> str:
    """Determine user's role for this event."""
    if source == "git":
        return "assignee"
    if source == "session":
        return "assignee"
    if source == "github":
        if event_type in ("pr_opened", "issue_opened"):
            return "reporter"
        if event_type == "pr_merged":
            return "assignee"
        if event_type == "pr_reviewed":
            return "contributor"
        return "assignee"
    if source == "gitlab":
        if event_type in ("mr_opened",):
            return "reporter"
        if event_type == "mr_merged":
            return "assignee"
        if event_type == "mr_review_given":
            return "contributor"
        if event_type == "mr_review_received":
            return "assignee"
        return "assignee"

    info = hierarchy_cache.get("issues", {}).get(item_id, {})
    reporter = (info.get("reporter") or "").lower()
    assignee = (info.get("assignee") or "").lower()

    user_lower = current_user.lower()
    email_lower = current_email.lower()

    is_reporter = user_lower in reporter or email_lower in reporter
    is_assignee = user_lower in assignee or email_lower in assignee

    if is_reporter and is_assignee:
        return "reporter"
    if is_reporter:
        return "reporter"
    if is_assignee:
        return "assignee"
    return "contributor"


def _build_classification_text(
    title: str,
    item_id: str,
    hierarchy_cache: dict,
) -> str:
    """Build enriched classification text from event title + Jira context."""
    parts = [title]
    info = hierarchy_cache.get("issues", {}).get(item_id, {})

    summary = info.get("summary", "")
    if summary and summary.lower() not in title.lower():
        parts.append(summary)

    description = info.get("description", "")
    if description:
        clean = re.sub(r"\{[^}]+\}|\[~[^\]]+\]|h[1-6]\.", "", description)
        parts.append(clean[:500])

    epic_key = info.get("epic", "")
    if epic_key:
        epic_info = hierarchy_cache.get("issues", {}).get(epic_key, {})
        epic_summary = epic_info.get("summary", "")
        if epic_summary:
            parts.append(f"Epic: {epic_summary}")

        anstrat_key = epic_info.get("parent_initiative", "")
        if anstrat_key:
            anstrat_info = hierarchy_cache.get("issues", {}).get(anstrat_key, {})
            anstrat_summary = anstrat_info.get("summary", "")
            if anstrat_summary:
                parts.append(f"ANSTRAT: {anstrat_summary}")

    return " ".join(parts)


def _build_hierarchy_metadata(item_id: str, hierarchy_cache: dict) -> dict:
    """Extract parent hierarchy metadata for an event."""
    info = hierarchy_cache.get("issues", {}).get(item_id, {})
    result: dict[str, str] = {}

    epic_key = info.get("epic", "")
    if epic_key:
        result["epic_key"] = epic_key
        epic_info = hierarchy_cache.get("issues", {}).get(epic_key, {})
        result["epic_summary"] = epic_info.get("summary", "")
        anstrat_key = epic_info.get("parent_initiative", "")
        if anstrat_key:
            result["anstrat_key"] = anstrat_key
            anstrat_info = hierarchy_cache.get("issues", {}).get(anstrat_key, {})
            result["anstrat_summary"] = anstrat_info.get("summary", "")

    return result


def _extract_jira_key(title: str) -> str:
    """Extract the primary Jira key from an event title.

    Matches any standard Jira key format (PROJECT-123). Prefers AAP/ANSTRAT
    keys when multiple are present.
    """
    aap_m = re.search(r"((?:AAP|ANSTRAT)-\d+)", title)
    if aap_m:
        return aap_m.group(1)
    m = re.search(r"([A-Z][A-Z0-9]+-\d+)", title)
    return m.group(1) if m else ""


def _jira_project_from_key(key: str) -> str:
    """Extract the project prefix from a Jira key (e.g. 'AAP' from 'AAP-12345')."""
    if "-" in key:
        return key.split("-", 1)[0]
    return ""


class DataCollector:
    def __init__(self):
        self._git_author_cache: str | None = None
        self._github_username_cache: str | None = None
        self._git_email_cache: str | None = None
        self._jira_username_cache: str | None = None
        self.hierarchy_cache: dict = {}
        self.strategy_index: dict = {}
        self.npu_classifier: object | None = None
        self._user_override: dict | None = None
        self._level_override: str | None = None

    def get_git_email(self) -> str:
        if self._git_email_cache is None:
            try:
                email = subprocess.check_output(
                    ["git", "config", "user.email"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                ).strip()
                self._git_email_cache = email or ""
            except Exception:
                self._git_email_cache = ""
        return self._git_email_cache

    def get_jira_username(self) -> str:
        if self._jira_username_cache is None:
            config_paths = [
                Path(__file__).parent.parent.parent / "config.json",
                AA_CONFIG_DIR / "config.json",
            ]
            username = ""
            for cfg_path in config_paths:
                try:
                    if cfg_path.exists():
                        with open(cfg_path, encoding="utf-8") as f:
                            config = json.load(f)
                        username = config.get("user", {}).get("jira_username", "")
                        if not username:
                            username = config.get("user", {}).get("username", "")
                        if username:
                            break
                except Exception:
                    continue
            self._jira_username_cache = username or self.get_git_author()
        return self._jira_username_cache

    def _enrich_event(
        self,
        event: dict,
        effective_defs: dict | None = None,
        min_signals: int | None = None,
    ) -> dict:
        """Add scope, role, classification_text, strategy alignment, and hierarchy to an event."""
        item_id = event.get("item_id", "")
        title = event.get("title", "")
        source = event.get("source", "")
        event_type = event.get("type", "")

        jira_key = (
            item_id if re.match(r"[A-Z]+-\d+$", item_id) else _extract_jira_key(title)
        )

        scope = (
            _detect_scope(jira_key, self.hierarchy_cache)
            if jira_key
            else ("commit" if source == "git" else "story")
        )
        current_user = self.get_jira_username()
        current_email = self.get_git_email()
        role = _detect_role(
            jira_key,
            source,
            event_type,
            self.hierarchy_cache,
            current_user,
            current_email,
        )

        classification_text = _build_classification_text(
            title, jira_key, self.hierarchy_cache
        )
        hierarchy = _build_hierarchy_metadata(jira_key, self.hierarchy_cache)

        strategy_cfg = get_strategy_alignment_config()
        min_overlap = strategy_cfg.get("min_text_overlap_words", 3)
        strategy_aligned, strategy_priorities = match_event_to_strategy(
            jira_key,
            hierarchy,
            classification_text,
            self.strategy_index,
            min_overlap,
        )

        if strategy_aligned and strategy_cfg.get("enrich_classification", True):
            for pname in strategy_priorities:
                prio_entry = next(
                    (
                        p
                        for p in self.strategy_index.get("priorities", [])
                        if p["name"] == pname
                    ),
                    None,
                )
                ctx = (
                    prio_entry["context"][:200]
                    if prio_entry and prio_entry.get("context")
                    else ""
                )
                classification_text += f" [Strategy: {pname}] {ctx}"

        if self._level_override:
            level = self._level_override
        else:
            cfg = get_merged_config()
            level = cfg.get("engineering_level", "sse")

        if self._user_override:
            current_user = self._user_override.get("jira_username", current_user)
            current_email = self._user_override.get("email", current_email)

        event["scope"] = scope
        event["role"] = role
        event["classification_text"] = classification_text
        event["strategy_aligned"] = strategy_aligned
        event["strategy_priorities"] = strategy_priorities
        event["hierarchy"] = hierarchy
        pts, sig_counts = map_competencies_with_signals(
            classification_text,
            source,
            event_type,
            scope,
            role,
            effective_defs=effective_defs,
            min_signals=min_signals,
            level=level,
            strategy_aligned=strategy_aligned,
            npu_classifier=self.npu_classifier,
            contribution_type=event.get("contribution_type"),
            is_cross_team=event.get("is_cross_team", False),
            review_decision=event.get("review_decision"),
        )
        event["points"] = pts
        event["signal_counts"] = sig_counts
        return event

    def get_perf_dir(self, year: int | None = None, quarter: int | None = None) -> Path:
        now = datetime.now()
        y = year or now.year
        q = quarter or ((now.month - 1) // 3 + 1)
        return PERFORMANCE_DIR / str(y) / f"q{q}" / "performance"

    def get_daily_dir(
        self, year: int | None = None, quarter: int | None = None
    ) -> Path:
        return self.get_perf_dir(year, quarter) / "daily"

    def get_config_repos(self) -> list[dict]:
        config_file = AA_CONFIG_DIR / "config.json"
        repos = []
        try:
            if config_file.exists():
                with open(config_file, encoding="utf-8") as f:
                    config = json.load(f)
                for name, repo_config in config.get("repositories", {}).items():
                    path = repo_config.get("path", "")
                    if path and Path(path).exists():
                        repos.append({"name": name, "path": path})
        except Exception:
            pass

        if not repos:
            common_paths = [
                Path.home() / "src" / "automation-analytics-backend",
                Path.home() / "src" / "app-interface",
                Path.home() / "src" / "redhat-ai-workflow",
            ]
            for p in common_paths:
                if p.exists():
                    repos.append({"name": p.name, "path": str(p)})
        return repos

    def get_git_author(self) -> str:
        if self._git_author_cache is None:
            try:
                name = subprocess.check_output(
                    ["git", "config", "user.name"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                ).strip()
                self._git_author_cache = name if name else os.environ.get("USER", "")
            except Exception:
                self._git_author_cache = os.environ.get("USER", "")
        return self._git_author_cache

    def get_github_username(self) -> str:
        if self._github_username_cache is None:
            username = ""
            config_paths = [
                Path(__file__).parent.parent.parent / "config.json",
                AA_CONFIG_DIR / "config.json",
            ]
            for cfg_path in config_paths:
                try:
                    if cfg_path.exists():
                        with open(cfg_path, encoding="utf-8") as f:
                            config = json.load(f)
                        username = config.get("user", {}).get("github_username", "")
                        if username:
                            break
                except Exception:
                    continue
            if not username:
                try:
                    output = subprocess.check_output(
                        ["gh", "auth", "status"],
                        text=True,
                        stderr=subprocess.STDOUT,
                        timeout=10,
                    )
                    for line in output.split("\n"):
                        if "Logged in to" in line and "account" in line:
                            parts = line.split("account")
                            if len(parts) > 1:
                                username = parts[1].strip().split()[0].strip("()")
                                break
                except Exception:
                    pass
            self._github_username_cache = username
            if username:
                logger.info(f"GitHub username: {username}")
            else:
                logger.warning("Could not determine GitHub username")
        return self._github_username_cache

    def _load_project_config(self) -> dict:
        """Load the project config.json, checking workspace then AA_CONFIG_DIR."""
        config_paths = [
            Path(__file__).parent.parent.parent / "config.json",
            AA_CONFIG_DIR / "config.json",
        ]
        for cfg_path in config_paths:
            try:
                if cfg_path.exists():
                    with open(cfg_path, encoding="utf-8") as f:
                        return json.load(f)
            except Exception:
                continue
        return {}

    def _get_gitlab_token(self) -> str:
        """Load GitLab private token from env or glab-cli config."""
        token = os.environ.get("GITLAB_TOKEN", "")
        if token:
            return token
        glab_config = Path.home() / ".config" / "glab-cli" / "config.yml"
        if glab_config.exists():
            try:
                import yaml

                with open(glab_config, encoding="utf-8") as fh:
                    gc = yaml.safe_load(fh)
                for host_data in gc.get("hosts", {}).values():
                    t = host_data.get("token", "")
                    if t:
                        return t
            except Exception:
                pass
        return ""

    def _get_gitlab_username(self, host: str, token: str) -> str:
        """Resolve the current GitLab username via API."""
        try:
            url = f"https://{host}/api/v4/user"
            req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read()).get("username", "")
        except Exception:
            return ""

    def _gitlab_api_get(self, host: str, token: str, path: str) -> list | dict:
        """Make a GET request to GitLab API, returning parsed JSON."""
        url = f"https://{host}/api/v4/{path}"
        req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    # ------------------------------------------------------------------
    # GitLab MR + Review collection (Stream 1)
    # ------------------------------------------------------------------

    def get_gitlab_cache(
        self, year: int, quarter: int, username_override: str = ""
    ) -> dict:
        """Fetch GitLab MRs and review activity for the quarter, with caching."""
        perf_dir = self.get_perf_dir(year, quarter)
        cache_suffix = f"_{username_override}" if username_override else ""
        cache_file = perf_dir / f"gitlab_event_cache{cache_suffix}.json"

        if cache_file.exists():
            try:
                mtime = cache_file.stat().st_mtime
                if time.time() - mtime < 3600:
                    with open(cache_file, encoding="utf-8") as f:
                        return json.load(f)
            except Exception:
                pass

        cfg = self._load_project_config()
        gitlab_host = cfg.get("gitlab", {}).get("host", "gitlab.cee.redhat.com")
        token = self._get_gitlab_token()
        if not token:
            logger.warning("No GitLab token – skipping GitLab collection")
            return {"mrs_authored": [], "reviews_given": [], "reviews_received": []}

        username = username_override or self._get_gitlab_username(gitlab_host, token)
        if not username:
            logger.warning("Could not determine GitLab username")
            return {"mrs_authored": [], "reviews_given": [], "reviews_received": []}

        quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        sm, _ = quarter_starts[quarter]
        q_start = f"{year}-{sm:02d}-01T00:00:00Z"
        if quarter < 4:
            nsm = quarter_starts[quarter + 1][0]
            q_end = f"{year}-{nsm:02d}-01T00:00:00Z"
        else:
            q_end = f"{year + 1}-01-01T00:00:00Z"

        repos = cfg.get("repositories", {})
        mrs_authored: list[dict] = []
        reviews_given: list[dict] = []
        reviews_received: list[dict] = []
        seen: set[str] = set()

        for repo_name, proj_cfg in repos.items():
            gl_path = proj_cfg.get("gitlab", "")
            if not gl_path or gl_path.startswith("github:"):
                continue
            encoded = urllib.parse.quote(gl_path, safe="")

            def _add_authored(
                mr_list: list[dict],
                _repo=repo_name,
                _gl_path=gl_path,
            ) -> None:
                for mr in mr_list:
                    uid = f"{_repo}:{mr['iid']}"
                    if uid in seen:
                        continue
                    seen.add(uid)
                    mrs_authored.append(
                        {
                            "project": _repo,
                            "gitlab_path": _gl_path,
                            "iid": mr["iid"],
                            "title": mr.get("title", ""),
                            "state": mr.get("state", ""),
                            "web_url": mr.get("web_url", ""),
                            "created_at": mr.get("created_at", ""),
                            "merged_at": mr.get("merged_at") or "",
                            "description": (mr.get("description") or "")[:200],
                        }
                    )

            # MRs authored by user created in the quarter
            try:
                _add_authored(
                    self._gitlab_api_get(
                        gitlab_host,
                        token,
                        f"projects/{encoded}/merge_requests"
                        f"?scope=all&author_username={username}"
                        f"&created_after={q_start}&created_before={q_end}&per_page=100",
                    )
                )
            except Exception as e:
                logger.debug(f"GitLab MR fetch (created) for {repo_name}: {e}")

            # Pre-quarter MRs still open
            try:
                _add_authored(
                    self._gitlab_api_get(
                        gitlab_host,
                        token,
                        f"projects/{encoded}/merge_requests"
                        f"?scope=all&author_username={username}"
                        f"&state=opened&per_page=100",
                    )
                )
            except Exception as e:
                logger.debug(f"GitLab MR fetch (open) for {repo_name}: {e}")

            # MRs merged during the quarter regardless of creation date
            try:
                _add_authored(
                    self._gitlab_api_get(
                        gitlab_host,
                        token,
                        f"projects/{encoded}/merge_requests"
                        f"?scope=all&author_username={username}"
                        f"&state=merged&updated_after={q_start}&updated_before={q_end}"
                        f"&per_page=100",
                    )
                )
            except Exception as e:
                logger.debug(f"GitLab MR fetch (merged) for {repo_name}: {e}")

            # Notes on recent MRs for review detection
            try:
                recent_mrs = self._gitlab_api_get(
                    gitlab_host,
                    token,
                    f"projects/{encoded}/merge_requests"
                    f"?scope=all&updated_after={q_start}&per_page=50&state=all",
                )
                for mr in recent_mrs:
                    mr_author = (mr.get("author", {}) or {}).get("username", "")
                    iid = mr["iid"]
                    try:
                        notes = self._gitlab_api_get(
                            gitlab_host,
                            token,
                            f"projects/{encoded}/merge_requests/{iid}/notes"
                            f"?per_page=100&sort=desc",
                        )
                    except Exception:
                        continue

                    for note in notes:
                        if note.get("system"):
                            continue
                        note_author = (note.get("author", {}) or {}).get("username", "")
                        note_created = note.get("created_at", "")
                        note_body = (note.get("body") or "")[:200]
                        note_id = note.get("id", "")

                        if note_author == username and mr_author != username:
                            reviews_given.append(
                                {
                                    "project": repo_name,
                                    "mr_iid": iid,
                                    "mr_title": mr.get("title", ""),
                                    "mr_web_url": mr.get("web_url", ""),
                                    "mr_author": mr_author,
                                    "note_id": note_id,
                                    "note_body": note_body,
                                    "created_at": note_created,
                                }
                            )
                        elif note_author != username and mr_author == username:
                            reviews_received.append(
                                {
                                    "project": repo_name,
                                    "mr_iid": iid,
                                    "mr_title": mr.get("title", ""),
                                    "mr_web_url": mr.get("web_url", ""),
                                    "reviewer": note_author,
                                    "note_id": note_id,
                                    "note_body": note_body,
                                    "created_at": note_created,
                                }
                            )
            except Exception as e:
                logger.debug(f"GitLab review fetch for {repo_name}: {e}")

        cache_data = {
            "mrs_authored": mrs_authored,
            "reviews_given": reviews_given,
            "reviews_received": reviews_received,
        }
        perf_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save GitLab cache: {e}")

        logger.info(
            f"GitLab: {len(mrs_authored)} MRs, "
            f"{len(reviews_given)} reviews given, "
            f"{len(reviews_received)} reviews received"
        )
        return cache_data

    def collect_gitlab_for_date(
        self, target: date, seen_ids: set[str], username_override: str = ""
    ) -> list[dict]:
        """Produce GitLab events for a specific date from the quarter cache."""
        year = target.year
        quarter = (target.month - 1) // 3 + 1
        target_str = target.isoformat()
        events: list[dict] = []
        cache = self.get_gitlab_cache(
            year, quarter, username_override=username_override
        )

        def _date_of(iso: str) -> str:
            return iso[:10] if iso else ""

        for mr in cache.get("mrs_authored", []):
            project = mr.get("project", "unknown")
            iid = mr.get("iid", 0)
            title = mr.get("title", "")
            state = mr.get("state", "")
            merged_at = mr.get("merged_at", "")
            created_at = mr.get("created_at", "")
            web_url = mr.get("web_url", "")

            if state == "merged" and _date_of(merged_at) == target_str:
                eid = f"gl-{project}-mr-{iid}-merged"
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    ev = {
                        "id": eid,
                        "source": "gitlab",
                        "type": "mr_merged",
                        "item_id": f"{project}!{iid}",
                        "title": f"[{project}] MR !{iid} merged: {title}",
                        "url": web_url,
                        "timestamp": merged_at,
                    }
                    events.append(self._enrich_event(ev))
            elif _date_of(created_at) == target_str:
                eid = f"gl-{project}-mr-{iid}-opened"
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    ev = {
                        "id": eid,
                        "source": "gitlab",
                        "type": "mr_opened",
                        "item_id": f"{project}!{iid}",
                        "title": f"[{project}] MR !{iid} opened: {title}",
                        "url": web_url,
                        "timestamp": created_at,
                    }
                    events.append(self._enrich_event(ev))

        # Deduplicate reviews per MR per day
        seen_review_mrs: set[str] = set()
        for review in cache.get("reviews_given", []):
            if _date_of(review.get("created_at", "")) != target_str:
                continue
            project = review.get("project", "unknown")
            iid = review.get("mr_iid", 0)
            dedup = f"gl-{project}-mr-{iid}-review-given"
            if dedup in seen_review_mrs or dedup in seen_ids:
                continue
            seen_review_mrs.add(dedup)
            seen_ids.add(dedup)
            ev = {
                "id": dedup,
                "source": "gitlab",
                "type": "mr_review_given",
                "item_id": f"{project}!{iid}",
                "title": f"[{project}] Reviewed MR !{iid}: {review.get('mr_title', '')}",
                "url": review.get("mr_web_url", ""),
                "timestamp": review.get("created_at", target_str),
            }
            events.append(self._enrich_event(ev))

        seen_received_mrs: set[str] = set()
        for review in cache.get("reviews_received", []):
            if _date_of(review.get("created_at", "")) != target_str:
                continue
            project = review.get("project", "unknown")
            iid = review.get("mr_iid", 0)
            dedup = f"gl-{project}-mr-{iid}-review-received"
            if dedup in seen_received_mrs or dedup in seen_ids:
                continue
            seen_received_mrs.add(dedup)
            seen_ids.add(dedup)
            reviewer = review.get("reviewer", "someone")
            ev = {
                "id": dedup,
                "source": "gitlab",
                "type": "mr_review_received",
                "item_id": f"{project}!{iid}",
                "title": (
                    f"[{project}] Review from {reviewer} on MR !{iid}: "
                    f"{review.get('mr_title', '')}"
                ),
                "url": review.get("mr_web_url", ""),
                "timestamp": review.get("created_at", target_str),
            }
            events.append(self._enrich_event(ev))

        return events

    # ------------------------------------------------------------------
    # Cross-project Jira collection (Stream 3)
    # ------------------------------------------------------------------

    def collect_jira_created_for_date(
        self, target: date, seen_ids: set[str], jira_user: str = ""
    ) -> list[dict]:
        """Collect Jira issues created by the user on the target date (any project)."""
        jira_date = target.strftime("%Y-%m-%d")
        events: list[dict] = []
        try:
            reporter_clause = (
                f"reporter = '{jira_user}'" if jira_user else "reporter = currentUser()"
            )
            jql = (
                f"created >= '{jira_date}' AND created < '{jira_date}' + 1d "
                f"AND {reporter_clause} "
                f"ORDER BY created DESC"
            )
            result = subprocess.check_output(
                ["rh-issue", "search", jql, "--max-results", "50"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=30,
                env={**os.environ, "HOME": str(Path.home())},
            )
            for match in re.finditer(
                r"([A-Z]+-\d+)\s*\|\s*\w+\s*\|\s*\w+[^|]*\|\s*\w+\s*\|\s*([^|]+)",
                result,
            ):
                key = match.group(1)
                summary = match.group(2).strip()[:100]
                event_id = f"jira:{key}:created"
                if event_id in seen_ids:
                    continue
                seen_ids.add(event_id)
                jira_proj = _jira_project_from_key(key)
                ev = {
                    "id": event_id,
                    "source": "jira",
                    "type": "issue_created",
                    "item_id": key,
                    "title": f"{key}: {summary}",
                    "timestamp": datetime.now().isoformat(),
                    "jira_project": jira_proj,
                    "is_cross_team": jira_proj not in ("AAP", "ANSTRAT"),
                }
                events.append(self._enrich_event(ev))
        except Exception as e:
            logger.debug(f"Jira created fetch failed: {e}")
        return events

    # ------------------------------------------------------------------
    # GitHub fork/upstream detection (Stream 2)
    # ------------------------------------------------------------------

    def _get_github_repo_metadata(self, year: int, quarter: int) -> dict:
        """Load or build a cache of GitHub repo fork/org metadata."""
        perf_dir = self.get_perf_dir(year, quarter)
        cache_file = perf_dir / "github_repo_metadata.json"
        if cache_file.exists():
            try:
                with open(cache_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_github_repo_metadata(self, year: int, quarter: int, meta: dict) -> None:
        perf_dir = self.get_perf_dir(year, quarter)
        perf_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(
                perf_dir / "github_repo_metadata.json", "w", encoding="utf-8"
            ) as f:
                json.dump(meta, f, indent=2)
        except Exception:
            pass

    def _resolve_github_repo_info(self, repo_name: str, meta: dict) -> dict:
        """Resolve fork/org info for a GitHub repo, caching per-repo."""
        if repo_name in meta:
            return meta[repo_name]
        info = {
            "is_fork": False,
            "parent_repo": None,
            "owner": repo_name.split("/")[0] if "/" in repo_name else "",
        }
        try:
            output = subprocess.check_output(
                ["gh", "api", f"repos/{repo_name}", "--jq", ".fork,.parent.full_name"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            lines = output.strip().split("\n")
            if lines:
                info["is_fork"] = lines[0].strip().lower() == "true"
            if len(lines) > 1 and lines[1].strip() and lines[1].strip() != "null":
                info["parent_repo"] = lines[1].strip()
        except Exception:
            pass
        meta[repo_name] = info
        return info

    def _classify_contribution(
        self, repo_name: str, repo_info: dict, github_username: str
    ) -> str:
        """Classify a GitHub contribution as upstream, fork, own, or cross-org."""
        owner = repo_info.get("owner", "")
        if repo_info.get("is_fork") and repo_info.get("parent_repo"):
            return "fork"
        if owner.lower() == github_username.lower():
            return "own"
        cfg = self._load_project_config()
        user_orgs = set()
        for _, rcfg in cfg.get("repositories", {}).items():
            gl = rcfg.get("gitlab", "")
            if gl.startswith("github:"):
                gh_path = gl.replace("github:", "")
                if "/" in gh_path:
                    user_orgs.add(gh_path.split("/")[0].lower())
        if owner.lower() in user_orgs:
            return "own"
        return "cross-org"

    def get_github_cache(
        self, year: int, quarter: int, username_override: str = ""
    ) -> dict:
        perf_dir = self.get_perf_dir(year, quarter)
        cache_suffix = f"_{username_override}" if username_override else ""
        cache_file = perf_dir / f"github_cache{cache_suffix}.json"

        if cache_file.exists():
            try:
                mtime = cache_file.stat().st_mtime
                age_secs = time.time() - mtime
                if age_secs < 3600:
                    with open(cache_file, encoding="utf-8") as f:
                        return json.load(f)
            except Exception:
                pass

        quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        sm, sd = quarter_starts[quarter]
        q_start = date(year, sm, sd)
        if quarter < 4:
            nm, nd = quarter_starts[quarter + 1]
            q_end = date(year, nm, nd) - timedelta(days=1)
        else:
            q_end = date(year, 12, 31)

        username = username_override or self.get_github_username()
        if not username:
            return {"prs_authored": [], "prs_reviewed": [], "issues_authored": []}

        date_range = f"{q_start.isoformat()}..{q_end.isoformat()}"
        json_fields = "repository,title,state,createdAt,closedAt,url,number"
        issue_fields = "repository,title,state,createdAt,closedAt,url,number"

        cache_data: dict[str, list] = {
            "prs_authored": [],
            "prs_reviewed": [],
            "issues_authored": [],
        }

        searches = [
            (
                "prs_authored",
                [
                    "gh",
                    "search",
                    "prs",
                    f"--author={username}",
                    f"--created={date_range}",
                    f"--json={json_fields}",
                    "--limit=100",
                ],
            ),
            (
                "prs_reviewed",
                [
                    "gh",
                    "search",
                    "prs",
                    f"--reviewed-by={username}",
                    f"--created={date_range}",
                    f"--json={json_fields}",
                    "--limit=100",
                ],
            ),
            (
                "issues_authored",
                [
                    "gh",
                    "search",
                    "issues",
                    f"--author={username}",
                    f"--created={date_range}",
                    f"--json={issue_fields}",
                    "--limit=100",
                ],
            ),
        ]

        for key, cmd in searches:
            try:
                output = subprocess.check_output(
                    cmd,
                    text=True,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
                results = json.loads(output) if output.strip() else []
                cache_data[key] = results
                logger.info(f"GitHub {key}: fetched {len(results)} results")
            except Exception as e:
                logger.warning(f"GitHub search failed for {key}: {e}")

        perf_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save GitHub cache: {e}")

        return cache_data

    def collect_github_for_date(
        self, target: date, seen_ids: set[str], username_override: str = ""
    ) -> list[dict]:
        year = target.year
        quarter = (target.month - 1) // 3 + 1
        target_str = target.isoformat()
        events: list[dict] = []

        cache = self.get_github_cache(
            year, quarter, username_override=username_override
        )
        repo_meta = self._get_github_repo_metadata(year, quarter)
        gh_username = username_override or self.get_github_username()
        meta_dirty = False

        def _parse_date(iso_str: str | None) -> str | None:
            if not iso_str:
                return None
            return iso_str[:10]

        def _add_contribution_fields(ev: dict, repo: str) -> dict:
            """Attach fork/upstream metadata to a GitHub event."""
            nonlocal meta_dirty
            info = self._resolve_github_repo_info(repo, repo_meta)
            if info != repo_meta.get(repo):
                meta_dirty = True
            ev["is_fork"] = info.get("is_fork", False)
            ev["parent_repo"] = info.get("parent_repo")
            ct = self._classify_contribution(repo, info, gh_username)
            ev["contribution_type"] = ct
            ev["is_external_org"] = ct in ("cross-org", "fork")
            return ev

        for pr in cache.get("prs_authored", []):
            repo = pr.get("repository", {}).get("nameWithOwner", "unknown")
            number = pr.get("number", 0)
            title = pr.get("title", "")
            state = (pr.get("state") or "").upper()
            created = _parse_date(pr.get("createdAt"))
            closed_raw = pr.get("closedAt", "")
            closed = (
                _parse_date(closed_raw)
                if closed_raw and not closed_raw.startswith("0001")
                else None
            )
            url = pr.get("url", "")

            if state == "MERGED" and closed and closed == target_str:
                event_id = f"gh-{repo}-pr-{number}-merged"
                if event_id not in seen_ids:
                    seen_ids.add(event_id)
                    ev = _add_contribution_fields(
                        {
                            "id": event_id,
                            "source": "github",
                            "type": "pr_merged",
                            "item_id": f"{repo}#{number}",
                            "title": f"[{repo}] PR #{number} merged: {title}",
                            "url": url,
                            "timestamp": closed_raw or target_str,
                        },
                        repo,
                    )
                    events.append(self._enrich_event(ev))
            elif created == target_str:
                event_id = f"gh-{repo}-pr-{number}-opened"
                if event_id not in seen_ids:
                    seen_ids.add(event_id)
                    ev = _add_contribution_fields(
                        {
                            "id": event_id,
                            "source": "github",
                            "type": "pr_opened",
                            "item_id": f"{repo}#{number}",
                            "title": f"[{repo}] PR #{number} opened: {title}",
                            "url": url,
                            "timestamp": pr.get("createdAt", target_str),
                        },
                        repo,
                    )
                    events.append(self._enrich_event(ev))

        for pr in cache.get("prs_reviewed", []):
            repo = pr.get("repository", {}).get("nameWithOwner", "unknown")
            number = pr.get("number", 0)
            title = pr.get("title", "")
            created = _parse_date(pr.get("createdAt"))
            url = pr.get("url", "")

            if created == target_str:
                event_id = f"gh-{repo}-pr-{number}-reviewed"
                if event_id not in seen_ids:
                    seen_ids.add(event_id)
                    ev = _add_contribution_fields(
                        {
                            "id": event_id,
                            "source": "github",
                            "type": "pr_reviewed",
                            "item_id": f"{repo}#{number}",
                            "title": f"[{repo}] Reviewed PR #{number}: {title}",
                            "url": url,
                            "timestamp": pr.get("createdAt", target_str),
                        },
                        repo,
                    )
                    # Stream 4: enrich with review decision
                    try:
                        review_out = subprocess.check_output(
                            [
                                "gh",
                                "pr",
                                "view",
                                str(number),
                                "-R",
                                repo,
                                "--json",
                                "reviews,reviewDecision",
                                "--jq",
                                f'.reviews[] | select(.author.login == "{gh_username}") | .state',
                            ],
                            text=True,
                            stderr=subprocess.DEVNULL,
                            timeout=10,
                        ).strip()
                        if review_out:
                            decisions = review_out.split("\n")
                            ev["review_decision"] = decisions[-1]
                    except Exception:
                        pass
                    events.append(self._enrich_event(ev))

        for issue in cache.get("issues_authored", []):
            repo = issue.get("repository", {}).get("nameWithOwner", "unknown")
            number = issue.get("number", 0)
            title = issue.get("title", "")
            state = (issue.get("state") or "").upper()
            created = _parse_date(issue.get("createdAt"))
            closed_raw = issue.get("closedAt", "")
            closed = (
                _parse_date(closed_raw)
                if closed_raw and not closed_raw.startswith("0001")
                else None
            )
            url = issue.get("url", "")

            if closed and closed == target_str:
                event_id = f"gh-{repo}-issue-{number}-closed"
                if event_id not in seen_ids:
                    seen_ids.add(event_id)
                    ev = _add_contribution_fields(
                        {
                            "id": event_id,
                            "source": "github",
                            "type": "issue_closed",
                            "item_id": f"{repo}#{number}",
                            "title": f"[{repo}] Issue #{number} closed: {title}",
                            "url": url,
                            "timestamp": issue.get("closedAt", target_str),
                        },
                        repo,
                    )
                    events.append(self._enrich_event(ev))
            elif created == target_str:
                event_id = f"gh-{repo}-issue-{number}-opened"
                if event_id not in seen_ids:
                    seen_ids.add(event_id)
                    ev = _add_contribution_fields(
                        {
                            "id": event_id,
                            "source": "github",
                            "type": "issue_opened",
                            "item_id": f"{repo}#{number}",
                            "title": f"[{repo}] Issue #{number} opened: {title}",
                            "url": url,
                            "timestamp": issue.get("createdAt", target_str),
                        },
                        repo,
                    )
                    events.append(self._enrich_event(ev))

        if meta_dirty:
            self._save_github_repo_metadata(year, quarter, repo_meta)

        return events

    # ------------------------------------------------------------------
    # Session log integration (Stream 6)
    # ------------------------------------------------------------------

    _SESSION_CLASSIFY_RULES: list[tuple[set[str], list[str], str]] = [
        # (matching entry types, text patterns, output event type)
        # Empty string matches entries with no type field
        ({"slack_alert"}, [], "alert_investigated"),
        ({"meet"}, [], "meeting_participated"),
        ({"slack_response", "slack_command"}, [], "collaboration_activity"),
        ({"summary"}, [], "session_documented"),
        (
            {"manual"},
            ["investigat", "alert", "prometheus", "firing"],
            "alert_investigated",
        ),
        (
            {"manual"},
            ["decision", "architecture", "chose", "evaluated", "design"],
            "architecture_decision",
        ),
        (
            {"manual"},
            ["debug", "root cause", "pipeline fix", "fixed pipeline"],
            "debugging_outcome",
        ),
        ({"manual"}, [], "collaboration_activity"),
        (
            {"tool"},
            ["reward zone"],
            "recognition_given",
        ),
        (
            {"cron"},
            ["slop", "cve", "review_all_prs", "pr_review"],
            "process_improvement",
        ),
    ]

    _TEXT_CLASSIFY_RULES: list[tuple[list[str], str]] = [
        (
            ["prometheus alert", "alert:", "investigated", "alert for", "firing"],
            "alert_investigated",
        ),
        (["meeting notes", "meeting:", "attendees:"], "meeting_participated"),
        (
            ["drafted slack", "slack reply", "slack update captured"],
            "collaboration_activity",
        ),
        (
            [
                "architecture update",
                "architecture decision",
                "decision:",
                "chose",
                "design review",
                "replaces",
            ],
            "architecture_decision",
        ),
        (
            ["fixed pipeline", "root cause", "debug", "pipeline fix"],
            "debugging_outcome",
        ),
        (["reward zone"], "recognition_given"),
        (
            [
                "slop scan",
                "cve_fix",
                "review_all_prs",
                "pr_review",
                "evening_slop_scan",
                "evening_pr_review",
                "morning_pr_review",
            ],
            "process_improvement",
        ),
        (
            ["updated", "jira issue", "attached session", "session closed"],
            "session_documented",
        ),
    ]

    def _classify_session_entry(self, entry: dict) -> str | None:
        """Classify a session log entry into a QC event type.

        Returns None if the entry should be skipped (noise).
        """
        cfg = get_session_integration_config()
        entry_type = entry.get("type", "")
        action = (entry.get("action") or "").lower()
        details = (entry.get("details") or "").lower()
        combined = f"{action} {details}"

        if entry_type in cfg.get("noise_skip_types", ["session"]):
            return None
        for pattern in cfg.get("noise_skip_patterns", []):
            if pattern.lower() in combined:
                return None
        min_len = cfg.get("min_details_length", 10)
        if len(entry.get("details") or "") < min_len and not entry_type:
            return None

        for type_set, patterns, event_type in self._SESSION_CLASSIFY_RULES:
            if entry_type not in type_set:
                continue
            if not patterns:
                return event_type
            if any(p in combined for p in patterns):
                return event_type

        if entry_type == "skill":
            skill_name = (entry.get("skill_name") or "").lower()
            if skill_name in (
                "hello_world",
                "vector_reindex",
                "vector_reindex_3h",
            ):
                return None
            return None

        if not entry_type:
            for patterns, event_type in self._TEXT_CLASSIFY_RULES:
                if any(p in combined for p in patterns):
                    return event_type

        return None

    @staticmethod
    def _extract_session_identifiers(entry: dict) -> tuple[list[str], list[str]]:
        """Extract Jira keys and MR IDs from a session entry for dedup."""
        action = entry.get("action") or ""
        details = entry.get("details") or ""
        issues = entry.get("issues") or []
        combined = f"{action} {details}"

        jira_keys = list(set(issues + re.findall(r"[A-Z][A-Z0-9]+-\d+", combined)))
        mr_ids = re.findall(r"!(\d+)", combined)

        return jira_keys, mr_ids

    def _collect_session_events(
        self,
        target: date,
        events: list[dict],
        seen_ids: set[str],
    ) -> list[dict]:
        """Collect events from session logs, deduplicating against existing events.

        For session entries that reference artifacts already captured by other
        collectors (Jira keys, MR IDs), the session text enriches the existing
        event's classification_text instead of creating a duplicate event.

        For entries with no overlap, new events with source="session" are created.
        """
        cfg = get_session_integration_config()
        if not cfg.get("enabled", True):
            return []

        session_file = (
            Path(__file__).parent.parent.parent
            / "memory"
            / "sessions"
            / f"{target.isoformat()}.yaml"
        )
        if not session_file.exists():
            return []

        try:
            with open(session_file, encoding="utf-8") as f:
                session_data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.debug(f"Session file read failed for {target}: {e}")
            return []

        entries = session_data.get("entries", [])
        if not entries:
            return []

        existing_item_ids: dict[str, dict] = {}
        for ev in events:
            item_id = ev.get("item_id", "")
            if item_id:
                existing_item_ids[item_id] = ev

        new_events: list[dict] = []
        target_str = target.isoformat()
        session_seq = 0

        for entry in entries:
            event_type = self._classify_session_entry(entry)
            if event_type is None:
                continue

            jira_keys, mr_ids = self._extract_session_identifiers(entry)
            action = entry.get("action") or ""
            details = entry.get("details") or ""
            entry_time = entry.get("time") or ""
            enhancement_text = f" [Session: {action}] {details}"

            overlapped = False
            for key in jira_keys:
                for suffix in ("resolved", "created"):
                    eid = f"jira:{key}:{suffix}"
                    if eid in seen_ids and key in existing_item_ids:
                        ct = existing_item_ids[key].get("classification_text", "")
                        existing_item_ids[key]["classification_text"] = (
                            ct + enhancement_text
                        )
                        overlapped = True
                        break
                if overlapped:
                    break

            if not overlapped:
                for mr_id in mr_ids:
                    for ev in events:
                        ev_item = ev.get("item_id", "")
                        if f"!{mr_id}" in ev_item or ev_item.endswith(f"!{mr_id}"):
                            ct = ev.get("classification_text", "")
                            ev["classification_text"] = ct + enhancement_text
                            overlapped = True
                            break
                    if overlapped:
                        break

            if overlapped:
                continue

            session_seq += 1
            event_id = f"session:{target_str}:{session_seq}"
            if event_id in seen_ids:
                continue
            seen_ids.add(event_id)

            primary_key = jira_keys[0] if jira_keys else ""
            if primary_key:
                _detect_scope(primary_key, self.hierarchy_cache)

            title_parts = [action or event_type]
            if details and details.lower() not in (action or "").lower():
                title_parts.append(details[:500])
            title = " ".join(title_parts)

            ev = {
                "id": event_id,
                "source": "session",
                "type": event_type,
                "item_id": primary_key,
                "title": title,
                "timestamp": (
                    f"{target_str}T{entry_time}" if entry_time else target_str
                ),
            }
            new_events.append(self._enrich_event(ev))

        if new_events:
            logger.info(f"Session: collected {len(new_events)} events for {target_str}")

        return new_events

    def collect_for_date(
        self, target: date, user_override: dict | None = None, level_override: str = ""
    ) -> dict:
        """Collect daily performance data for a given date.

        When user_override is provided, collects data for that user instead
        of the current user. Used for peer comparison data capture.
        user_override keys: git_author, jira_username, gitlab_username, github_username
        """
        self._user_override = user_override
        self._level_override = level_override or None
        try:
            return self._collect_for_date_impl(target, user_override)
        finally:
            self._user_override = None
            self._level_override = None

    def _collect_for_date_impl(
        self, target: date, user_override: dict | None = None
    ) -> dict:
        year = target.year
        quarter = (target.month - 1) // 3 + 1
        quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        start_month, start_day = quarter_starts[quarter]
        quarter_start = date(year, start_month, start_day)
        day_of_quarter = (target - quarter_start).days + 1

        events: list[dict] = []
        seen_ids: set[str] = set()
        target_str = target.isoformat()

        git_author = (
            user_override["git_author"] if user_override else self.get_git_author()
        )
        repos = self.get_config_repos()
        for repo in repos:
            try:
                cmd = [
                    "git",
                    "-C",
                    repo["path"],
                    "log",
                    f"--since={target_str} 00:00:00",
                    f"--until={target_str} 23:59:59",
                    f"--author={git_author}",
                    "--format=%H|%s|%ad",
                    "--date=iso",
                ]
                output = subprocess.check_output(
                    cmd, text=True, stderr=subprocess.DEVNULL, timeout=15
                )
                for line in output.strip().split("\n"):
                    if not line:
                        continue
                    parts = line.split("|", 2)
                    if len(parts) < 2:
                        continue
                    sha = parts[0][:8]
                    message = parts[1]
                    ts = parts[2] if len(parts) > 2 else target_str
                    event_id = f"git:{repo['name']}:{sha}"
                    if event_id in seen_ids:
                        continue
                    seen_ids.add(event_id)
                    title = f"[{repo['name']}] {message}"
                    ev = {
                        "id": event_id,
                        "source": "git",
                        "type": "commit",
                        "item_id": sha,
                        "title": title,
                        "timestamp": ts,
                    }
                    events.append(self._enrich_event(ev))
            except Exception as e:
                logger.debug(f"Git collect failed for {repo['name']}: {e}")

        jira_user = user_override.get("jira_username", "") if user_override else ""
        jira_date = target.strftime("%Y-%m-%d")
        try:
            if jira_user:
                assignee_clause = (
                    f"(assignee = '{jira_user}' OR reporter = '{jira_user}')"
                )
            else:
                assignee_clause = (
                    "(assignee = currentUser() OR reporter = currentUser())"
                )
            jql = (
                f"resolved >= '{jira_date}' AND resolved < '{jira_date}' + 1d "
                f"AND {assignee_clause} "
                f"ORDER BY resolved DESC"
            )
            result = subprocess.check_output(
                ["rh-issue", "search", jql, "--max-results", "50"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=30,
                env={**os.environ, "HOME": str(Path.home())},
            )
            for match in re.finditer(
                r"([A-Z]+-\d+)\s*\|\s*\w+\s*\|\s*\w+[^|]*\|\s*\w+\s*\|\s*([^|]+)",
                result,
            ):
                key = match.group(1)
                summary = match.group(2).strip()[:100]
                event_id = f"jira:{key}:resolved"
                if event_id in seen_ids:
                    continue
                seen_ids.add(event_id)
                title = f"{key}: {summary}"
                jira_proj = _jira_project_from_key(key)
                ev = {
                    "id": event_id,
                    "source": "jira",
                    "type": "issue_resolved",
                    "item_id": key,
                    "title": title,
                    "timestamp": datetime.now().isoformat(),
                    "jira_project": jira_proj,
                    "is_cross_team": jira_proj not in ("AAP", "ANSTRAT"),
                }
                events.append(self._enrich_event(ev))
        except Exception as e:
            logger.debug(f"Jira resolved fetch failed: {e}")

        gh_user = user_override.get("github_username", "") if user_override else ""
        try:
            gh_events = self.collect_github_for_date(
                target, seen_ids, username_override=gh_user
            )
            events.extend(gh_events)
            if gh_events:
                logger.info(
                    f"GitHub: collected {len(gh_events)} events for {target_str}"
                )
        except Exception as e:
            logger.debug(f"GitHub collect failed: {e}")

        gl_user = user_override.get("gitlab_username", "") if user_override else ""
        try:
            gl_events = self.collect_gitlab_for_date(
                target, seen_ids, username_override=gl_user
            )
            events.extend(gl_events)
            if gl_events:
                logger.info(
                    f"GitLab: collected {len(gl_events)} events for {target_str}"
                )
        except Exception as e:
            logger.debug(f"GitLab collect failed: {e}")

        jira_created_user = jira_user
        try:
            jira_created = self.collect_jira_created_for_date(
                target, seen_ids, jira_user=jira_created_user
            )
            events.extend(jira_created)
            if jira_created:
                logger.info(
                    f"Jira created: collected {len(jira_created)} events for {target_str}"
                )
        except Exception as e:
            logger.debug(f"Jira created collect failed: {e}")

        if not user_override:
            try:
                perf_dir = self.get_perf_dir(target.year, (target.month - 1) // 3 + 1)
                new_email_ids = collect_executive_emails_for_date(target, perf_dir)
                if new_email_ids:
                    logger.info(
                        f"Gmail: cached {len(new_email_ids)} executive emails for {target_str}"
                    )
            except Exception as e:
                logger.warning(f"Executive email collect failed (non-blocking): {e}")

            try:
                session_events = self._collect_session_events(target, events, seen_ids)
                events.extend(session_events)
            except Exception as e:
                logger.debug(f"Session collect failed (non-blocking): {e}")

        _, _, daily_cap, _ = get_effective_defs()
        daily_points: dict[str, int] = {}
        for event in events:
            for comp_id, pts in event.get("points", {}).items():
                current = daily_points.get(comp_id, 0)
                daily_points[comp_id] = min(current + pts, daily_cap)

        daily_data = {
            "date": target_str,
            "day_of_quarter": day_of_quarter,
            "events": events,
            "daily_points": daily_points,
            "daily_total": sum(daily_points.values()),
            "saved_at": datetime.now().isoformat(),
        }

        if user_override:
            peer_name = user_override.get("username", "unknown")
            peer_dir = self.get_perf_dir(year, quarter) / "peers" / peer_name / "daily"
            peer_dir.mkdir(parents=True, exist_ok=True)
            daily_file = peer_dir / f"{target_str}.json"
        else:
            daily_dir = self.get_daily_dir(year, quarter)
            daily_dir.mkdir(parents=True, exist_ok=True)
            daily_file = daily_dir / f"{target_str}.json"

        with open(daily_file, "w", encoding="utf-8") as f:
            json.dump(daily_data, f, indent=2)

        return daily_data
