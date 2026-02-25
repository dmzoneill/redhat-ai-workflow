import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from server.paths import AA_CONFIG_DIR, PERFORMANCE_DIR
from server.utils import run_cmd_sync
from services.stats.email_parser import collect_executive_emails_for_date
from services.stats.gdrive_collector import (
    collect_gdrive_contributions,
    collect_shared_drive_peer_contributions,
)
from services.stats.meeting_collector import (
    collect_meeting_contributions,
    collect_meeting_peer_contributions,
)
from services.stats.quarter_utils import QUARTER_STARTS
from services.stats.scorer import (
    get_effective_defs,
    get_merged_config,
    get_session_integration_config,
    get_strategy_alignment_config,
    map_competencies_with_signals,
)
from services.stats.strategy import match_event_to_strategy

logger = logging.getLogger(__name__)


class _CircuitBreaker:
    """Skip a source after consecutive failures to avoid wasting time on timeouts."""

    def __init__(self, threshold: int = 3, cooldown: float = 300):
        self._threshold = threshold
        self._cooldown = cooldown
        self._failures: dict[str, int] = {}
        self._tripped_at: dict[str, float] = {}

    def record_failure(self, source: str) -> None:
        self._failures[source] = self._failures.get(source, 0) + 1
        if self._failures[source] >= self._threshold:
            self._tripped_at[source] = time.monotonic()
            logger.warning(
                "Circuit breaker tripped for %s after %d failures (cooldown %ds)",
                source,
                self._failures[source],
                self._cooldown,
            )

    def record_success(self, source: str) -> None:
        self._failures.pop(source, None)
        self._tripped_at.pop(source, None)

    def is_open(self, source: str) -> bool:
        tripped = self._tripped_at.get(source)
        if tripped is None:
            return False
        if time.monotonic() - tripped > self._cooldown:
            self._tripped_at.pop(source, None)
            self._failures.pop(source, None)
            logger.info("Circuit breaker reset for %s after cooldown", source)
            return False
        return True


_circuit = _CircuitBreaker(threshold=3, cooldown=300)


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


_MEETING_SCOPE_OVERRIDES: list[tuple[str, str]] = [
    ("architecture_review", "epic"),
    ("cross_team", "epic"),
    ("customer_meeting", "epic"),
    ("sprint_planning", "story"),
    ("sprint_review", "story"),
    ("planning", "epic"),
    ("retrospective", "story"),
    ("presentation", "story"),
    ("interview", "story"),
    ("training", "story"),
    ("code_review", "story"),
    ("incident_response", "story"),
    ("onboarding", "story"),
]


def _detect_meeting_scope(event_type: str) -> str:
    """Determine scope for a meeting event based on its classification.

    High-impact meetings (architecture reviews, cross-team, planning,
    customer meetings) use epic scope (mult 4).  Mid-impact meetings
    (sprint ceremonies, presentations, training) use story scope (mult 2).
    Routine meetings (standups, 1:1s, general) stay at meeting scope (mult 1).

    Order matters: more specific patterns (sprint_planning) are checked
    before less specific ones (planning) to avoid substring false matches.
    """
    for classification, scope in _MEETING_SCOPE_OVERRIDES:
        if classification in event_type:
            return scope
    return "meeting"


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
    if source == "gdrive":
        if "created" in event_type:
            return "assignee"
        return "contributor"
    if source == "meeting":
        if "organized" in event_type:
            return "assignee"
        return "contributor"
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


def _jira_rest_search(
    jql: str,
    fields: str = "key,summary,resolutiondate,created",
    max_results: int = 200,
) -> list[dict] | None:
    """Search Jira via REST API. Returns list of issue dicts or None on failure.

    Requires JIRA_JPAT (or JIRA_TOKEN) and JIRA_URL env vars.
    """
    token = os.environ.get("JIRA_JPAT", "") or os.environ.get("JIRA_TOKEN", "")
    if not token:
        return None
    base_url = os.environ.get("JIRA_URL", "https://issues.redhat.com").rstrip("/")
    params = urllib.parse.urlencode(
        {
            "jql": jql,
            "maxResults": max_results,
            "fields": fields,
        }
    )
    url = f"{base_url}/rest/api/2/search?{params}"
    try:
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("issues", [])
    except Exception as e:
        logger.warning("Jira REST search failed (jql=%s): %s", jql[:80], e)
        return None


class DataCollector:
    def __init__(self):
        self._git_author_cache: str | None = None
        self._github_username_cache: str | None = None
        self._git_email_cache: str | None = None
        self._jira_username_cache: str | None = None
        self.hierarchy_cache: dict = {}
        self.strategy_index: dict = {}
        self.npu_classifier: object | None = None
        self._thread_local = threading.local()
        self._jira_quarter_cache: dict[str, dict[str, list[dict]]] = {}
        self._jira_quarter_lock = threading.Lock()
        self._hierarchy_lock = threading.Lock()
        self._hierarchy_tried: set[str] = set()

    @property
    def _user_override(self) -> dict | None:
        return getattr(self._thread_local, "user_override", None)

    @_user_override.setter
    def _user_override(self, value: dict | None) -> None:
        self._thread_local.user_override = value

    @property
    def _level_override(self) -> str | None:
        return getattr(self._thread_local, "level_override", None)

    @_level_override.setter
    def _level_override(self, value: str | None) -> None:
        self._thread_local.level_override = value

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
            except Exception as e:
                logger.warning("Failed to get git user.email: %s", e)
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
                except Exception as e:
                    logger.warning(
                        "Failed to read jira_username from %s: %s", cfg_path, e
                    )
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

        if source == "meeting":
            scope = _detect_meeting_scope(event_type)
        elif source == "gdrive":
            scope = "doc"
        elif jira_key:
            scope = _detect_scope(jira_key, self.hierarchy_cache)
        elif source == "git":
            scope = "commit"
        else:
            scope = "story"
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
        if source == "gdrive" and event.get("gdrive_role"):
            gdrive_role = event["gdrive_role"]
            role = "assignee" if gdrive_role == "owner" else "contributor"
        if source == "meeting" and event.get("meeting_role"):
            role = event["meeting_role"]

        classification_text = _build_classification_text(
            title, jira_key, self.hierarchy_cache
        )
        extra = event.get("extra_classification_text", "")
        if extra:
            classification_text += " " + extra
        hierarchy = _build_hierarchy_metadata(jira_key, self.hierarchy_cache)

        strategy_cfg = get_strategy_alignment_config()
        min_overlap = strategy_cfg.get("min_text_overlap_words", 4)
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

    @staticmethod
    def _get_repo_cache_dir() -> Path:
        cache_dir = AA_CONFIG_DIR / "performance" / "repo-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def _gitlab_path_to_ssh_url(self, gitlab_path: str) -> str:
        """Convert a GitLab project path to an SSH clone URL."""
        cfg = self._load_project_config()
        host = cfg.get("gitlab", {}).get("host", "gitlab.cee.redhat.com")
        return f"git@{host}:{gitlab_path}.git"

    @staticmethod
    def _github_path_to_ssh_url(github_path: str) -> str:
        return f"git@github.com:{github_path}.git"

    _repo_update_times: dict[str, float] = {}
    _resolved_repo_cache: dict[str, str | None] = {}
    _repo_update_lock = threading.Lock()
    REPO_UPDATE_INTERVAL = 3600
    LOCAL_SRC_DIR = Path.home() / "src"
    _SSH_ENV = {
        **os.environ,
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
    }

    @classmethod
    def _repo_basename(cls, gitlab_path: str) -> str:
        """Extract the repo basename from a GitLab/GitHub path."""
        clean = gitlab_path.replace("github:", "")
        return clean.split("/")[-1] if "/" in clean else clean

    @classmethod
    def _find_local_repo(cls, gitlab_path: str) -> str | None:
        """Check ~/src/ for a local checkout matching a GitLab/GitHub path."""
        basename = cls._repo_basename(gitlab_path)
        local = cls.LOCAL_SRC_DIR / basename
        if local.is_dir() and (local / ".git").exists():
            return str(local)
        return None

    @staticmethod
    def _is_working_copy_clean(repo_path: str) -> bool:
        """Return True if the git working copy has no uncommitted changes."""
        try:
            out = subprocess.check_output(
                ["git", "-C", repo_path, "status", "--porcelain"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            return out.strip() == ""
        except Exception as e:
            logger.warning("git status --porcelain failed for %s: %s", repo_path, e)
            return False

    def _safe_pull_rebase(self, repo_path: str, name: str) -> bool:
        """Pull latest via rebase if working copy is clean. Returns success."""
        if not self._is_working_copy_clean(repo_path):
            logger.debug("Repo %s has uncommitted changes -- skipping pull", name)
            return False
        try:
            subprocess.check_output(
                ["git", "-C", repo_path, "pull", "--rebase", "--quiet"],
                text=True,
                stderr=subprocess.PIPE,
                timeout=60,
                env=self._SSH_ENV,
            )
            return True
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            if "CONFLICT" in stderr or "could not apply" in stderr:
                logger.warning("Rebase conflict in %s -- aborting rebase", name)
                try:
                    subprocess.check_output(
                        ["git", "-C", repo_path, "rebase", "--abort"],
                        text=True,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
                except Exception as abort_err:
                    logger.error(
                        "git rebase --abort failed for %s (repo may be in bad state): %s",
                        name,
                        abort_err,
                    )
            else:
                logger.warning("Pull --rebase failed for %s: %s", name, stderr)
            return False
        except Exception as e:
            logger.warning("Pull --rebase failed for %s: %s", name, e)
            return False

    def _ensure_repo_available(
        self,
        gitlab_path: str,
        skip_update: bool = False,
    ) -> str | None:
        """Ensure a repo is available for git log. Returns the path or None.

        Resolution order:
        1. Existing checkout in ~/src/{basename} -- pull --rebase if clean
        2. Clone full checkout into ~/src/{basename} via SSH
        3. Legacy bare clone in repo-cache/ (read-only fallback)

        skip_update=True skips pull/fetch (for the per-day loop where repos
        were already updated at the per-peer level).
        Updates are throttled to once per REPO_UPDATE_INTERVAL seconds.
        """
        if gitlab_path in self._resolved_repo_cache:
            cached = self._resolved_repo_cache[gitlab_path]
            if cached is not None:
                return cached

        basename = self._repo_basename(gitlab_path)
        target_dir = self.LOCAL_SRC_DIR / basename

        if target_dir.is_dir() and (target_dir / ".git").exists():
            path = str(target_dir)
            self._resolved_repo_cache[gitlab_path] = path
            if skip_update:
                return path
            with self._repo_update_lock:
                last = self._repo_update_times.get(path, 0)
                if (time.monotonic() - last) >= self.REPO_UPDATE_INTERVAL:
                    self._repo_update_times[path] = time.monotonic()
                    need_update = True
                else:
                    need_update = False
            if need_update:
                if self._safe_pull_rebase(path, basename):
                    logger.debug("Updated repo %s via pull --rebase", basename)
            return path

        if gitlab_path.startswith("github:"):
            ssh_url = self._github_path_to_ssh_url(gitlab_path[7:])
        else:
            ssh_url = self._gitlab_path_to_ssh_url(gitlab_path)

        self.LOCAL_SRC_DIR.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.check_output(
                ["git", "clone", "--quiet", ssh_url, str(target_dir)],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=180,
                env=self._SSH_ENV,
            )
            logger.info("Cloned %s into ~/src/%s", gitlab_path, basename)
            path = str(target_dir)
            with self._repo_update_lock:
                self._repo_update_times[path] = time.monotonic()
            self._resolved_repo_cache[gitlab_path] = path
            return path
        except Exception as e:
            logger.warning("Failed to clone %s into ~/src/: %s", gitlab_path, e)

        cache_dir = self._get_repo_cache_dir()
        flat_name = gitlab_path.replace("github:", "").replace("/", "__")
        bare_dir = cache_dir / f"{flat_name}.git"
        if bare_dir.exists():
            if self._is_bare_repo_valid(str(bare_dir)):
                path = str(bare_dir)
                self._resolved_repo_cache[gitlab_path] = path
                return path
            else:
                import shutil

                logger.warning("Removing corrupt bare repo %s", bare_dir.name)
                shutil.rmtree(bare_dir, ignore_errors=True)

        self._resolved_repo_cache[gitlab_path] = None
        return None

    @staticmethod
    def _is_bare_repo_valid(repo_path: str) -> bool:
        """Check a bare repo has a valid HEAD (not pointing to .invalid)."""
        try:
            out = subprocess.check_output(
                ["git", "-C", repo_path, "rev-parse", "--verify", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            return len(out.strip()) >= 7
        except Exception as e:
            logger.warning("Bare repo validation failed for %s: %s", repo_path, e)
            return False

    def get_config_repos(self, include_cached: bool = False) -> list[dict]:
        config_file = AA_CONFIG_DIR / "config.json"
        repos = []
        seen_names: set[str] = set()
        try:
            if config_file.exists():
                with open(config_file, encoding="utf-8") as f:
                    config = json.load(f)
                for name, repo_config in config.get("repositories", {}).items():
                    path = repo_config.get("path", "")
                    if path and Path(path).exists():
                        repos.append({"name": name, "path": path})
                        seen_names.add(name)
                    elif include_cached:
                        gl_path = repo_config.get("gitlab", "")
                        if gl_path:
                            resolved = self._ensure_repo_available(
                                gl_path, skip_update=True
                            )
                            if resolved:
                                repos.append({"name": name, "path": resolved})
                                seen_names.add(name)
        except Exception as e:
            logger.error(
                "Failed to load config.json repos (falling back to common paths): %s", e
            )

        if not repos:
            common_paths = [
                Path.home() / "src" / "automation-analytics-backend",
                Path.home() / "src" / "app-interface",
                Path.home() / "src" / "redhat-ai-workflow",
            ]
            for p in common_paths:
                if p.exists():
                    repos.append({"name": p.name, "path": str(p)})
                    seen_names.add(p.name)

        if include_cached:
            cache_dir = self._get_repo_cache_dir()
            if cache_dir.exists():
                for bare in cache_dir.iterdir():
                    if bare.is_dir() and bare.name.endswith(".git"):
                        name = bare.name[:-4]
                        if name not in seen_names:
                            repos.append({"name": name, "path": str(bare)})
                            seen_names.add(name)

        return repos

    def discover_peer_repos(self, gitlab_paths: list[str]) -> None:
        """Pre-cache repos discovered from peer GitLab/GitHub MR data."""
        for gl_path in gitlab_paths:
            if not gl_path:
                continue
            self._ensure_repo_available(gl_path)

    def prepare_peer_repos(
        self,
        peer: dict,
        year: int,
        quarter: int,
    ) -> list[dict]:
        """Discover and return the repo list for a peer -- call once per peer.

        Fetches GitLab/GitHub caches, discovers repos via SSH clone into
        ~/src/, and returns a list of {"name": ..., "path": ...} dicts
        ready for git log.  Resolution order per repo:
        1. Existing checkout in ~/src/  (pull --rebase if clean)
        2. Clone full checkout into ~/src/ via SSH
        3. Legacy bare clone in repo-cache/ (read-only fallback)
        """
        peer_repo_paths: list[str] = []
        gl_user = peer.get("gitlab_username", "")
        if gl_user:
            gl_cache = self.get_gitlab_cache(year, quarter, username_override=gl_user)
            for mr in gl_cache.get("mrs_authored", []):
                p = mr.get("gitlab_path", "")
                if p:
                    peer_repo_paths.append(p)
        gh_user = peer.get("github_username", "")
        if gh_user:
            gh_cache = self.get_github_cache(year, quarter, username_override=gh_user)
            for pr in gh_cache.get("prs_authored", []):
                repo = (pr.get("repository") or {}).get("nameWithOwner", "")
                if repo:
                    peer_repo_paths.append(f"github:{repo}")

        repos = self.get_config_repos(include_cached=False)
        seen_paths: set[str] = {r["path"] for r in repos}
        seen_names: set[str] = {r["name"] for r in repos}

        unique_paths = list(set(peer_repo_paths))[:20]
        existing_count = 0
        cloned_count = 0
        for gl_path in unique_paths:
            basename = self._repo_basename(gl_path)
            if basename in seen_names:
                continue

            resolved = self._ensure_repo_available(gl_path)
            if resolved and resolved not in seen_paths:
                repos.append({"name": basename, "path": resolved})
                seen_paths.add(resolved)
                seen_names.add(basename)
                if "src" in resolved and ".git" not in resolved:
                    existing_count += 1
                else:
                    cloned_count += 1

        logger.info(
            "prepare_peer_repos(%s): %d existing in ~/src, %d newly cloned, %d total repos",
            peer.get("username", "?"),
            existing_count,
            cloned_count,
            len(repos),
        )
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
            except Exception as e:
                logger.warning(
                    "Failed to get git user.name, falling back to $USER: %s", e
                )
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
                except Exception as e:
                    logger.warning(
                        "Failed to read github_username from %s: %s", cfg_path, e
                    )
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
                except Exception as e:
                    logger.warning(
                        "gh auth status failed, cannot determine GitHub username: %s", e
                    )
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
            except Exception as e:
                logger.warning("Failed to load project config from %s: %s", cfg_path, e)
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
            except Exception as e:
                logger.warning("Failed to read GitLab token from glab config: %s", e)
        return ""

    def _get_gitlab_username(self, host: str, token: str) -> str:
        """Resolve the current GitLab username via API."""
        try:
            url = f"https://{host}/api/v4/user"
            req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read()).get("username", "")
        except Exception as e:
            logger.warning("GitLab API /user failed for %s: %s", host, e)
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

    _gitlab_mem_cache: dict[str, tuple[float, dict]] = {}
    _gitlab_mem_lock = threading.Lock()

    def get_gitlab_cache(
        self, year: int, quarter: int, username_override: str = ""
    ) -> dict:
        """Fetch GitLab MRs and review activity for the quarter, with caching."""
        perf_dir = self.get_perf_dir(year, quarter)
        cache_suffix = f"_{username_override}" if username_override else ""
        cache_file = perf_dir / f"gitlab_event_cache{cache_suffix}.json"
        mem_key = str(cache_file)

        _MEM_TTL = 3600
        _DISK_TTL = 86400

        with self._gitlab_mem_lock:
            if mem_key in self._gitlab_mem_cache:
                ts, data = self._gitlab_mem_cache[mem_key]
                if time.time() - ts < _MEM_TTL:
                    return data

        if cache_file.exists():
            try:
                mtime = cache_file.stat().st_mtime
                if time.time() - mtime < _DISK_TTL:
                    with open(cache_file, encoding="utf-8") as f:
                        cached = json.load(f)
                    if cached.get("mrs_authored") or not username_override:
                        with self._gitlab_mem_lock:
                            self._gitlab_mem_cache[mem_key] = (time.time(), cached)
                        return cached
            except Exception as e:
                logger.warning(
                    "Failed to read GitLab cache %s (will re-fetch from API): %s",
                    cache_file,
                    e,
                )

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

        quarter_starts = QUARTER_STARTS
        sm, _ = quarter_starts[quarter]
        q_start = f"{year}-{sm:02d}-01T00:00:00Z"
        if quarter < 4:
            nsm = quarter_starts[quarter + 1][0]
            q_end = f"{year}-{nsm:02d}-01T00:00:00Z"
        else:
            q_end = f"{year + 1}-01-01T00:00:00Z"

        mrs_authored: list[dict] = []
        reviews_given: list[dict] = []
        reviews_received: list[dict] = []
        seen: set[str] = set()

        if username_override:
            cache_data = self._fetch_gitlab_global(
                gitlab_host, token, username, q_start, q_end
            )
        else:
            cache_data = self._fetch_gitlab_per_repo(
                cfg,
                gitlab_host,
                token,
                username,
                q_start,
                q_end,
                mrs_authored,
                reviews_given,
                reviews_received,
                seen,
            )

        has_data = bool(
            cache_data.get("mrs_authored")
            or cache_data.get("reviews_given")
            or cache_data.get("reviews_received")
        )

        if has_data or not username_override:
            perf_dir.mkdir(parents=True, exist_ok=True)
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save GitLab cache: {e}")

            with self._gitlab_mem_lock:
                self._gitlab_mem_cache[str(cache_file)] = (time.time(), cache_data)
        elif username_override:
            logger.info(
                "GitLab peer:%s returned no data -- skipping cache write "
                "(VPN down or no GitLab activity)",
                username,
            )

        who = f"peer:{username}" if username_override else username
        logger.info(
            f"GitLab ({who}): {len(cache_data.get('mrs_authored', []))} MRs, "
            f"{len(cache_data.get('reviews_given', []))} reviews given, "
            f"{len(cache_data.get('reviews_received', []))} reviews received"
        )
        return cache_data

    def _fetch_gitlab_global(
        self,
        host: str,
        token: str,
        username: str,
        q_start: str,
        q_end: str,
    ) -> dict:
        """Fetch GitLab MRs and reviews for a peer using global search."""
        mrs_authored: list[dict] = []
        reviews_given: list[dict] = []
        reviews_received: list[dict] = []
        seen: set[str] = set()

        def _parse_mr_meta(mr: dict) -> tuple[str, str]:
            """Extract project_path and project_name from a global MR result."""
            web_url = mr.get("web_url", "")
            project_path = ""
            project_name = "unknown"
            ref = mr.get("references", {})
            if ref and ref.get("full"):
                project_name = ref["full"].rsplit("!", 1)[0]
                project_path = project_name
            elif web_url:
                parts = web_url.split("/-/merge_requests/")
                if len(parts) == 2:
                    path = parts[0].replace(f"https://{host}/", "")
                    project_path = path
                    project_name = path.rsplit("/", 1)[-1] if "/" in path else path
            return project_path, project_name

        def _add_global_mr(mr: dict) -> None:
            project_path, project_name = _parse_mr_meta(mr)
            iid = mr.get("iid", 0)
            uid = f"{project_path}:{iid}"
            if uid in seen:
                return
            seen.add(uid)
            mrs_authored.append(
                {
                    "project": project_name,
                    "gitlab_path": project_path,
                    "iid": iid,
                    "title": mr.get("title", ""),
                    "state": mr.get("state", ""),
                    "web_url": mr.get("web_url", ""),
                    "created_at": mr.get("created_at", ""),
                    "merged_at": mr.get("merged_at") or "",
                    "description": (mr.get("description") or "")[:200],
                }
            )

        endpoints = [
            (
                f"merge_requests?scope=all&author_username={username}"
                f"&created_after={q_start}&created_before={q_end}"
                f"&per_page=100"
            ),
            (
                f"merge_requests?scope=all&author_username={username}"
                f"&state=merged&updated_after={q_start}&updated_before={q_end}"
                f"&per_page=100"
            ),
            (
                f"merge_requests?scope=all&author_username={username}"
                f"&state=opened&updated_after={q_start}"
                f"&per_page=100"
            ),
            (
                f"merge_requests?scope=all&author_username={username}"
                f"&state=closed&updated_after={q_start}&updated_before={q_end}"
                f"&per_page=100"
            ),
        ]
        for endpoint in endpoints:
            page = 1
            while page <= 5:
                paged = f"{endpoint}&page={page}"
                try:
                    batch = self._gitlab_api_get(host, token, paged)
                    if not batch:
                        break
                    for mr in batch:
                        _add_global_mr(mr)
                    if len(batch) < 100:
                        break
                    page += 1
                except Exception as e:
                    logger.info(f"GitLab global MR fetch for {username}: {e}")
                    break

        for mr_data in mrs_authored[:15]:
            gl_path = mr_data.get("gitlab_path", "")
            if not gl_path:
                continue
            encoded = urllib.parse.quote(gl_path, safe="")
            iid = mr_data["iid"]
            try:
                notes = self._gitlab_api_get(
                    host,
                    token,
                    f"projects/{encoded}/merge_requests/{iid}/notes"
                    f"?per_page=20&sort=desc",
                )
            except Exception as e:
                logger.warning(
                    "GitLab notes fetch failed for %s MR !%s: %s", gl_path, iid, e
                )
                continue
            for note in notes:
                if note.get("system"):
                    continue
                note_author = (note.get("author", {}) or {}).get("username", "")
                if note_author and note_author != username:
                    reviews_received.append(
                        {
                            "project": mr_data["project"],
                            "mr_iid": iid,
                            "mr_title": mr_data["title"],
                            "mr_web_url": mr_data.get("web_url", ""),
                            "reviewer": note_author,
                            "note_id": note.get("id", ""),
                            "note_body": (note.get("body") or "")[:200],
                            "created_at": note.get("created_at", ""),
                        }
                    )

        cfg = self._load_project_config()
        team_repos = cfg.get("repositories", {})
        for repo_name, proj_cfg in team_repos.items():
            gl_path = proj_cfg.get("gitlab", "")
            if not gl_path or gl_path.startswith("github:"):
                continue
            encoded = urllib.parse.quote(gl_path, safe="")
            try:
                notes_page = self._gitlab_api_get(
                    host,
                    token,
                    f"projects/{encoded}/merge_requests"
                    f"?scope=all&reviewer_username={username}"
                    f"&updated_after={q_start}&per_page=20&state=all",
                )
            except Exception as e:
                logger.warning(
                    "GitLab reviewer MR list failed for %s: %s", repo_name, e
                )
                continue
            for mr in notes_page:
                mr_author = (mr.get("author", {}) or {}).get("username", "")
                if mr_author == username:
                    continue
                reviews_given.append(
                    {
                        "project": repo_name,
                        "mr_iid": mr.get("iid", 0),
                        "mr_title": mr.get("title", ""),
                        "mr_web_url": mr.get("web_url", ""),
                        "mr_author": mr_author,
                        "note_id": "",
                        "note_body": "",
                        "created_at": mr.get("updated_at", ""),
                    }
                )

        return {
            "mrs_authored": mrs_authored,
            "reviews_given": reviews_given,
            "reviews_received": reviews_received,
        }

    def _fetch_gitlab_per_repo(
        self,
        cfg: dict,
        gitlab_host: str,
        token: str,
        username: str,
        q_start: str,
        q_end: str,
        mrs_authored: list[dict],
        reviews_given: list[dict],
        reviews_received: list[dict],
        seen: set[str],
    ) -> dict:
        """Fetch GitLab MRs by iterating configured repos (for the current user)."""
        repos = cfg.get("repositories", {})

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
                    except Exception as e:
                        logger.warning(
                            "GitLab notes fetch failed for %s MR !%s: %s",
                            gl_path,
                            iid,
                            e,
                        )
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

        return {
            "mrs_authored": mrs_authored,
            "reviews_given": reviews_given,
            "reviews_received": reviews_received,
        }

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
            mr_description = (mr.get("description") or "").strip()

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
                    if mr_description:
                        ev["extra_classification_text"] = mr_description[:300]
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
                    if mr_description:
                        ev["extra_classification_text"] = mr_description[:300]
                    events.append(self._enrich_event(ev))

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
            note_body = (review.get("note_body") or "").strip()
            ev = {
                "id": dedup,
                "source": "gitlab",
                "type": "mr_review_given",
                "item_id": f"{project}!{iid}",
                "title": f"[{project}] Reviewed MR !{iid}: {review.get('mr_title', '')}",
                "url": review.get("mr_web_url", ""),
                "timestamp": review.get("created_at", target_str),
            }
            if note_body:
                ev["extra_classification_text"] = f"review comment: {note_body[:200]}"
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
            note_body = (review.get("note_body") or "").strip()
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
            if note_body:
                ev["extra_classification_text"] = f"review comment: {note_body[:200]}"
            events.append(self._enrich_event(ev))

        return events

    # ------------------------------------------------------------------
    # Cross-project Jira collection (Stream 3)
    # ------------------------------------------------------------------

    def prefetch_jira_quarter(
        self, jira_user: str, year: int, quarter: int
    ) -> dict[str, list[dict]]:
        """Pre-fetch all Jira events for a user for the entire quarter via REST API.

        Returns a dict keyed by date string (YYYY-MM-DD) with lists of
        pre-built event dicts. Replaces ~110 per-day subprocess calls
        with 2-3 REST API calls for the whole quarter.
        """
        cache_key = f"{jira_user}:{year}:Q{quarter}"
        with self._jira_quarter_lock:
            if cache_key in self._jira_quarter_cache:
                return self._jira_quarter_cache[cache_key]

        if _circuit.is_open("jira"):
            with self._jira_quarter_lock:
                self._jira_quarter_cache[cache_key] = {}
            return {}

        quarter_starts = QUARTER_STARTS
        sm, _ = quarter_starts[quarter]
        q_start = date(year, sm, 1).isoformat()
        if quarter < 4:
            nm, _ = quarter_starts[quarter + 1]
            q_end = date(year, nm, 1).isoformat()
        else:
            q_end = date(year + 1, 1, 1).isoformat()

        events_by_date: dict[str, list[dict]] = {}
        # Red Hat Jira REST API expects email format (user@redhat.com) for assignee/reporter
        jira_lookup = (
            f"{jira_user}@redhat.com"
            if jira_user and "@" not in jira_user
            else jira_user
        )
        user_clause = (
            f"(assignee = '{jira_lookup}' OR reporter = '{jira_lookup}')"
            if jira_user
            else "(assignee = currentUser() OR reporter = currentUser())"
        )
        reporter_clause = (
            f"reporter = '{jira_lookup}'" if jira_user else "reporter = currentUser()"
        )

        queries = [
            (
                "issue_resolved",
                "resolved",
                "resolutiondate",
                f"resolved >= '{q_start}' AND resolved < '{q_end}' "
                f"AND {user_clause} ORDER BY resolved DESC",
            ),
            (
                "issue_created",
                "created",
                "created",
                f"created >= '{q_start}' AND created < '{q_end}' "
                f"AND {reporter_clause} ORDER BY created DESC",
            ),
        ]

        # Prefer REST API: we get resolutiondate/created to partition by date
        rest_used = False
        for event_type, id_suffix, date_field, jql in queries:
            issues = _jira_rest_search(
                jql,
                fields=f"key,summary,{date_field}",
                max_results=200,
            )
            if issues is not None:
                rest_used = True
                _circuit.record_success("jira")
                issue_count = 0
                for raw in issues:
                    key = raw.get("key", "")
                    if not re.match(r"^[A-Z]+-\d+$", key):
                        continue
                    fields_data = raw.get("fields", raw)
                    summary = (fields_data.get("summary") or "")[:100]
                    date_val = None
                    if date_field == "resolutiondate":
                        date_val = fields_data.get("resolutiondate")
                    else:
                        date_val = fields_data.get("created")
                    # Extract YYYY-MM-DD from ISO datetime
                    if date_val:
                        date_str = date_val[:10] if len(date_val) >= 10 else q_start
                    else:
                        date_str = q_start
                    issue_count += 1
                    jira_proj = _jira_project_from_key(key)
                    ev = {
                        "id": f"jira:{key}:{id_suffix}",
                        "source": "jira",
                        "type": event_type,
                        "item_id": key,
                        "title": f"{key}: {summary}",
                        "timestamp": f"{date_str}T00:00:00",
                        "jira_project": jira_proj,
                        "is_cross_team": jira_proj not in ("AAP", "ANSTRAT"),
                    }
                    events_by_date.setdefault(date_str, []).append(ev)
                logger.info(
                    "Jira quarter prefetch %s for %s via REST: %d issues",
                    event_type,
                    jira_user or "self",
                    issue_count,
                )

        # Fallback to per-day rh-issue when REST fails (e.g. no JIRA_JPAT)
        # rh-issue table output has no resolutiondate/created, so we must query per day
        if not rest_used and jira_user:
            q_start_d = date.fromisoformat(q_start)
            q_end_d = date.fromisoformat(q_end)
            day = q_start_d
            while day < q_end_d:
                day_str = day.isoformat()
                day_next = (day + timedelta(days=1)).isoformat()
                for event_type, id_suffix, date_field, _ in queries:
                    try:
                        if date_field == "resolutiondate":
                            jql = (
                                f"resolved >= '{day_str}' AND resolved < '{day_next}' "
                                f"AND {user_clause} ORDER BY resolved DESC"
                            )
                        else:
                            jql = (
                                f"created >= '{day_str}' AND created < '{day_next}' "
                                f"AND {reporter_clause} ORDER BY created DESC"
                            )
                        ok, result = run_cmd_sync(
                            ["rh-issue", "search", jql, "--max-results", "50"],
                            timeout=30,
                        )
                        if not ok:
                            raise RuntimeError(result)
                        _circuit.record_success("jira")
                        for line in result.splitlines():
                            parts = [p.strip() for p in line.split("|")]
                            if len(parts) < 5:
                                continue
                            key = parts[0]
                            if not re.match(r"^[A-Z]+-\d+$", key):
                                continue
                            summary = (parts[4] if len(parts) > 4 else "")[:100]
                            jira_proj = _jira_project_from_key(key)
                            ev = {
                                "id": f"jira:{key}:{id_suffix}",
                                "source": "jira",
                                "type": event_type,
                                "item_id": key,
                                "title": f"{key}: {summary}",
                                "timestamp": f"{day_str}T00:00:00",
                                "jira_project": jira_proj,
                                "is_cross_team": jira_proj not in ("AAP", "ANSTRAT"),
                            }
                            events_by_date.setdefault(day_str, []).append(ev)
                    except Exception as e:
                        _circuit.record_failure("jira")
                        logger.debug(
                            "Jira prefetch %s %s failed: %s", day_str, event_type, e
                        )
                day += timedelta(days=1)
            total = sum(len(v) for v in events_by_date.values())
            if total:
                logger.info(
                    "Jira quarter prefetch for %s via rh-issue (per-day): %d issues",
                    jira_user,
                    total,
                )

        with self._jira_quarter_lock:
            self._jira_quarter_cache[cache_key] = events_by_date
        return events_by_date

    def collect_jira_created_for_date(
        self, target: date, seen_ids: set[str], jira_user: str = ""
    ) -> list[dict]:
        """Collect Jira issues created by the user on the target date (any project).

        For peers (jira_user set), the quarter is pre-fetched via REST API
        in prefetch_jira_quarter() and events are already included in
        collect_for_date. This method handles the current user's own data
        via the rh-issue CLI.
        """
        if jira_user:
            return []
        if _circuit.is_open("jira"):
            return []
        jira_date = target.strftime("%Y-%m-%d")
        jira_next = (target + timedelta(days=1)).strftime("%Y-%m-%d")
        events: list[dict] = []
        try:
            jql = (
                f"created >= '{jira_date}' AND created < '{jira_next}' "
                f"AND reporter = currentUser() "
                f"ORDER BY created DESC"
            )
            ok, result = run_cmd_sync(
                ["rh-issue", "search", jql, "--max-results", "50"],
                timeout=30,
            )
            if not ok:
                raise RuntimeError(result)
            _circuit.record_success("jira")
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
            _circuit.record_failure("jira")
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
            except Exception as e:
                logger.warning(
                    "Failed to read GitHub repo metadata cache %s: %s", cache_file, e
                )
        return {}

    def _save_github_repo_metadata(self, year: int, quarter: int, meta: dict) -> None:
        perf_dir = self.get_perf_dir(year, quarter)
        perf_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(
                perf_dir / "github_repo_metadata.json", "w", encoding="utf-8"
            ) as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save GitHub repo metadata: %s", e)

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
        except Exception as e:
            logger.warning("gh api repos/%s failed: %s", repo_name, e)
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

    _github_mem_cache: dict[str, tuple[float, dict]] = {}
    _github_mem_lock = threading.Lock()

    def get_github_cache(
        self, year: int, quarter: int, username_override: str = ""
    ) -> dict:
        perf_dir = self.get_perf_dir(year, quarter)
        cache_suffix = f"_{username_override}" if username_override else ""
        cache_file = perf_dir / f"github_cache{cache_suffix}.json"
        mem_key = str(cache_file)

        _MEM_TTL = 3600
        _DISK_TTL = 86400

        with self._github_mem_lock:
            if mem_key in self._github_mem_cache:
                ts, data = self._github_mem_cache[mem_key]
                if time.time() - ts < _MEM_TTL:
                    return data

        if cache_file.exists():
            try:
                mtime = cache_file.stat().st_mtime
                age_secs = time.time() - mtime
                if age_secs < _DISK_TTL:
                    with open(cache_file, encoding="utf-8") as f:
                        cached = json.load(f)
                    with self._github_mem_lock:
                        self._github_mem_cache[mem_key] = (time.time(), cached)
                    return cached
            except Exception as e:
                logger.warning(
                    "Failed to read GitHub cache %s (will re-fetch from API): %s",
                    cache_file,
                    e,
                )

        quarter_starts = QUARTER_STARTS
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

        cache_data = self._fetch_github_graphql(username, date_range)

        has_data = bool(
            cache_data.get("prs_authored")
            or cache_data.get("prs_reviewed")
            or cache_data.get("issues_authored")
        )

        if has_data or not username_override:
            perf_dir.mkdir(parents=True, exist_ok=True)
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save GitHub cache: {e}")

            with self._github_mem_lock:
                self._github_mem_cache[str(cache_file)] = (time.time(), cache_data)
        elif username_override:
            logger.info(
                "GitHub peer:%s returned no data -- skipping cache write",
                username,
            )

        return cache_data

    def _fetch_github_graphql(self, username: str, date_range: str) -> dict[str, list]:
        """Fetch all GitHub activity for a user via multiple GraphQL calls.

        Searches by created, merged, and closed date ranges to capture all
        quarter activity, not just PRs created during the window.
        """
        pr_fragment = """
    nodes {
      ... on PullRequest {
        repository { nameWithOwner }
        title state createdAt closedAt mergedAt url number
        reviews(first: 20) {
          nodes { author { login } state }
        }
      }
    }"""
        issue_fragment = """
    nodes {
      ... on Issue {
        repository { nameWithOwner }
        title state createdAt closedAt url number
      }
    }"""

        search_sets = [
            {
                "authored": f"type:pr author:{username} created:{date_range}",
                "reviewed": f"type:pr reviewed-by:{username} created:{date_range}",
                "issues": f"type:issue author:{username} created:{date_range}",
            },
            {
                "authored": f"type:pr author:{username} merged:{date_range}",
                "reviewed": f"type:pr reviewed-by:{username} merged:{date_range}",
                "issues": f"type:issue author:{username} closed:{date_range}",
            },
            {
                "authored": f"type:pr author:{username} closed:{date_range}",
                "reviewed": "",
                "issues": "",
            },
            {
                "authored": f"type:pr author:{username} updated:{date_range} is:open",
                "reviewed": f"type:pr reviewed-by:{username} updated:{date_range}",
                "issues": "",
            },
        ]

        all_authored: dict[str, dict] = {}
        all_reviewed: dict[str, dict] = {}
        all_issues: dict[str, dict] = {}

        for search_vars in search_sets:
            parts = []
            gql_vars: dict[str, str] = {}
            var_decls = []
            if search_vars.get("authored"):
                var_decls.append("$authored: String!")
                gql_vars["authored"] = search_vars["authored"]
                parts.append(
                    f"  prs_authored: search(query: $authored, type: ISSUE, first: 100) {{{pr_fragment}\n  }}"
                )
            if search_vars.get("reviewed"):
                var_decls.append("$reviewed: String!")
                gql_vars["reviewed"] = search_vars["reviewed"]
                parts.append(
                    f"  prs_reviewed: search(query: $reviewed, type: ISSUE, first: 100) {{{pr_fragment}\n  }}"
                )
            if search_vars.get("issues"):
                var_decls.append("$issues: String!")
                gql_vars["issues"] = search_vars["issues"]
                parts.append(
                    f"  issues_authored: search(query: $issues, type: ISSUE, first: 100) {{{issue_fragment}\n  }}"
                )
            if not parts:
                continue

            query = f"query({', '.join(var_decls)}) {{\n" + "\n".join(parts) + "\n}"
            cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
            for k, v in gql_vars.items():
                cmd.extend(["-f", f"{k}={v}"])
            try:
                output = subprocess.check_output(
                    cmd,
                    text=True,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
                data = json.loads(output).get("data", {})
            except Exception as e:
                logger.debug("GitHub GraphQL search failed for %s: %s", username, e)
                continue

            for node in data.get("prs_authored", {}).get("nodes", []):
                if not node or not node.get("url"):
                    continue
                key = node["url"]
                if key not in all_authored:
                    reviews_raw = node.pop("reviews", {}).get("nodes", [])
                    node["_reviews"] = [
                        {"login": r["author"]["login"], "state": r["state"]}
                        for r in reviews_raw
                        if r and r.get("author")
                    ]
                    all_authored[key] = node

            for node in data.get("prs_reviewed", {}).get("nodes", []):
                if not node or not node.get("url"):
                    continue
                key = node["url"]
                if key not in all_reviewed:
                    reviews_raw = node.pop("reviews", {}).get("nodes", [])
                    node["_reviews"] = [
                        {"login": r["author"]["login"], "state": r["state"]}
                        for r in reviews_raw
                        if r and r.get("author")
                    ]
                    all_reviewed[key] = node

            for node in data.get("issues_authored", {}).get("nodes", []):
                if not node or not node.get("url"):
                    continue
                key = node["url"]
                if key not in all_issues:
                    all_issues[key] = node

        prs_authored = list(all_authored.values())
        prs_reviewed = list(all_reviewed.values())
        issues_authored = list(all_issues.values())

        logger.info(
            "GitHub GraphQL: %d authored, %d reviewed, %d issues for %s",
            len(prs_authored),
            len(prs_reviewed),
            len(issues_authored),
            username,
        )

        if not prs_authored and not prs_reviewed and not issues_authored:
            return self._fetch_github_rest_fallback(username, date_range)

        return {
            "prs_authored": prs_authored,
            "prs_reviewed": prs_reviewed,
            "issues_authored": issues_authored,
        }

    def _fetch_github_rest_fallback(
        self, username: str, date_range: str
    ) -> dict[str, list]:
        """Fallback to 3 separate REST searches if GraphQL fails."""
        json_fields = "repository,title,state,createdAt,closedAt,url,number"
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
                    f"--json={json_fields}",
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
                    user_reviews = [
                        r["state"]
                        for r in pr.get("_reviews", [])
                        if r.get("login") == gh_username
                    ]
                    if user_reviews:
                        ev["review_decision"] = user_reviews[-1]
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
        ({"slack_alert"}, [], "alert_investigated"),
        ({"meet"}, [], "meeting_participated"),
        ({"slack_response", "slack_command"}, [], "collaboration_activity"),
        ({"summary"}, [], "session_documented"),
        (
            {"manual"},
            ["investigat", "alert", "prometheus", "firing", "incident"],
            "alert_investigated",
        ),
        (
            {"manual"},
            [
                "decision",
                "architecture",
                "chose",
                "evaluated",
                "design",
                "rfc",
                "proposal",
                "trade-off",
                "tradeoff",
            ],
            "architecture_decision",
        ),
        (
            {"manual"},
            [
                "debug",
                "root cause",
                "pipeline fix",
                "fixed pipeline",
                "diagnosed",
                "troubleshoot",
                "stack trace",
            ],
            "debugging_outcome",
        ),
        (
            {"manual"},
            [
                "customer",
                "stakeholder",
                "partner",
                "vendor",
                "demo",
                "field escalation",
                "user request",
                "billing",
                "tenant",
                "user-facing",
                "customer-reported",
            ],
            "customer_engagement",
        ),
        (
            {"manual"},
            [
                "led",
                "drove",
                "facilitated",
                "coordinated",
                "mentored",
                "initiative lead",
                "roadmap",
                "cross-team",
            ],
            "leadership_activity",
        ),
        (
            {"manual"},
            [
                "feedback",
                "shared",
                "pair",
                "mob",
                "review",
                "answered",
                "helped",
                "collaborated",
                "coordinated",
            ],
            "collaboration_activity",
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
        (
            ["meeting notes", "meeting:", "attendees:", "sprint planning"],
            "meeting_participated",
        ),
        (
            [
                "customer",
                "stakeholder",
                "partner",
                "vendor",
                "demo",
                "field escalation",
                "billing issue",
                "tenant",
                "user-facing",
                "customer-reported",
            ],
            "customer_engagement",
        ),
        (
            [
                "led",
                "drove",
                "facilitated",
                "coordinated",
                "mentored",
                "initiative lead",
                "roadmap",
                "cross-team",
                "tech lead",
            ],
            "leadership_activity",
        ),
        (
            [
                "drafted slack",
                "slack reply",
                "slack update captured",
                "feedback",
                "shared",
                "pair programm",
                "reviewed",
                "answered",
                "helped",
                "collaborated",
            ],
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
                "rfc",
                "proposal",
                "trade-off",
                "evaluated options",
            ],
            "architecture_decision",
        ),
        (
            [
                "fixed pipeline",
                "root cause",
                "debug",
                "pipeline fix",
                "diagnosed",
                "troubleshoot",
                "stack trace",
            ],
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
                "refactor",
                "tech debt",
                "automated",
                "streamlined",
                "improvement",
                "cleanup",
                "migration",
            ],
            "process_improvement",
        ),
        (
            [
                "updated",
                "jira issue",
                "attached session",
                "session closed",
                "accomplished",
                "completed",
                "delivered",
                "shipped",
                "addressed feedback",
                "resolved",
            ],
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
            _SKILL_NOISE = {
                "hello_world",
                "vector_reindex",
                "vector_reindex_3h",
                "reindex_all_vectors",
                "nightly_jira_hygiene",
            }
            if skill_name in _SKILL_NOISE:
                return None
            _SKILL_EVENT_MAP = {
                "cve_fix": "process_improvement",
                "slop_scan": "process_improvement",
                "slop_fix": "process_improvement",
                "slop_scan_now": "process_improvement",
                "cleanup_branches": "process_improvement",
                "check_ci_health": "process_improvement",
                "ci_retry": "process_improvement",
                "review_all_prs": "process_improvement",
                "investigate_alert": "alert_investigated",
                "investigate_slack_alert": "alert_investigated",
                "debug_prod": "alert_investigated",
                "review_pr": "collaboration_activity",
                "review_local_changes": "collaboration_activity",
                "check_mr_feedback": "collaboration_activity",
                "check_my_prs": "collaboration_activity",
                "notify_mr": "collaboration_activity",
                "reward_zone": "recognition_given",
                "create_mr": "session_documented",
                "start_work": "session_documented",
                "close_issue": "session_documented",
                "jira_hygiene": "session_documented",
                "jira_hygiene_all": "session_documented",
                "sprint_planning": "meeting_participated",
                "schedule_meeting": "meeting_participated",
                "research_topic": "architecture_decision",
                "plan_implementation": "architecture_decision",
                "learn_architecture": "architecture_decision",
                "gather_context": "architecture_decision",
                "compare_options": "architecture_decision",
                "deploy_to_ephemeral": "session_documented",
                "test_mr_ephemeral": "session_documented",
                "environment_overview": "session_documented",
                "release_to_prod": "session_documented",
                "release_aa_backend_prod": "session_documented",
            }
            return _SKILL_EVENT_MAP.get(skill_name)

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

            extra_parts = []
            if entry.get("type") == "summary":
                for field in ("accomplished", "decisions", "next_steps"):
                    val = entry.get(field)
                    if isinstance(val, list):
                        extra_parts.extend(str(v) for v in val)
                    elif isinstance(val, str) and val:
                        extra_parts.append(val)
                files_changed = entry.get("files_changed")
                if isinstance(files_changed, list):
                    extra_parts.extend(str(f) for f in files_changed)
                elif isinstance(files_changed, str) and files_changed:
                    extra_parts.append(files_changed)

            summary_extra = " ".join(extra_parts)
            enhancement_text = f" [Session: {action}] {details}"
            if summary_extra:
                enhancement_text += f" {summary_extra}"

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
            if summary_extra:
                ev["extra_classification_text"] = summary_extra[:500]
            new_events.append(self._enrich_event(ev))

        if new_events:
            logger.info(f"Session: collected {len(new_events)} events for {target_str}")

        return new_events

    def _fetch_missing_hierarchy(self, events: list[dict]) -> int:
        """Fetch Jira hierarchy for AAP keys found in events but missing from cache.

        Traces each AAP key up to its epic and ANSTRAT initiative, enriching
        the shared hierarchy_cache so all events (including peer events) get
        full classification text with summary, description, epic, and strategy context.

        Returns the number of new keys added to the cache.
        """
        with self._hierarchy_lock:
            existing = self.hierarchy_cache.get("issues", {})
            missing_keys: set[str] = set()
            for ev in events:
                title = ev.get("title", "")
                for key in re.findall(r"(AAP-\d+)", title):
                    if key not in existing and key not in self._hierarchy_tried:
                        missing_keys.add(key)

            if not missing_keys:
                return 0

            self._hierarchy_tried.update(missing_keys)

        added = 0
        epic_keys: set[str] = set()

        for key in list(missing_keys)[:20]:
            try:
                ok, result = run_cmd_sync(
                    ["rh-issue", "view-issue", key],
                    timeout=15,
                )
                if not ok:
                    raise RuntimeError(result)
                info: dict[str, str] = {"key": key}
                for line in result.split("\n"):
                    m = re.match(
                        r"^([a-z][a-z_ /]+?)\s*:\s*(.*)$",
                        line.strip(),
                        re.IGNORECASE,
                    )
                    if m:
                        field = m.group(1).strip().lower().replace(" ", "_")
                        val = m.group(2).strip()
                        if field in ("summary", "status"):
                            info[field] = val
                        if field in ("issue_type", "issuetype"):
                            info["issue_type"] = val
                        if field in ("epic_link", "epic", "parent"):
                            info["epic"] = val
                        if field in ("reporter", "assignee", "assigned_to"):
                            info[field.replace("assigned_to", "assignee")] = val
                        if field == "description":
                            info["description"] = val[:500]
                with self._hierarchy_lock:
                    if "issues" not in self.hierarchy_cache:
                        self.hierarchy_cache["issues"] = {}
                    self.hierarchy_cache["issues"][key] = info
                added += 1

                epic_key = info.get("epic", "")
                if (
                    epic_key
                    and epic_key.startswith("AAP-")
                    and epic_key not in existing
                ):
                    epic_keys.add(epic_key)
            except Exception as e:
                logger.warning("Hierarchy fetch failed for %s: %s", key, e)
                continue

        for epic_key in epic_keys:
            if epic_key in self.hierarchy_cache.get("issues", {}):
                continue
            try:
                ok, result = run_cmd_sync(
                    ["rh-issue", "view-issue", epic_key],
                    timeout=15,
                )
                if not ok:
                    raise RuntimeError(result)
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
                            einfo["summary"] = val
                        if field in ("epic_link", "epic", "parent"):
                            einfo["parent_initiative"] = val
                with self._hierarchy_lock:
                    self.hierarchy_cache["issues"][epic_key] = einfo
                added += 1
            except Exception as e:
                logger.warning("Hierarchy fetch failed for epic %s: %s", epic_key, e)
                continue

        if added:
            logger.info(
                "Hierarchy enrichment: fetched %d new issue%s (%d requested)",
                added,
                "s" if added != 1 else "",
                len(missing_keys),
            )
        return added

    def _re_enrich_events(self, events: list[dict]) -> list[dict]:
        """Re-enrich events after the hierarchy cache has been updated."""
        for i, ev in enumerate(events):
            events[i] = self._enrich_event(
                {
                    k: v
                    for k, v in ev.items()
                    if k
                    not in (
                        "scope",
                        "role",
                        "classification_text",
                        "strategy_aligned",
                        "strategy_priorities",
                        "hierarchy",
                        "points",
                        "signal_counts",
                    )
                }
            )
        return events

    def collect_for_date(
        self,
        target: date,
        user_override: dict | None = None,
        level_override: str = "",
        sources: list[str] | None = None,
        peer_repos: list[dict] | None = None,
    ) -> dict:
        """Collect daily performance data for a given date.

        When user_override is provided, collects data for that user instead
        of the current user. Used for peer comparison data capture.
        user_override keys: git_author, jira_username, gitlab_username, github_username, email

        sources: optional list of data sources to collect. Valid values:
        "git", "jira", "gitlab", "github", "gdrive", "meeting". When set,
        only those sources are re-collected and the results are merged with
        the existing daily file (events from other sources are preserved).
        None means collect all.

        peer_repos: pre-computed list of repos for this peer (avoids
        re-discovering repos on every day). Each entry is {"name": ..., "path": ...}.
        """
        self._user_override = user_override
        self._level_override = level_override or None
        try:
            return self._collect_for_date_impl(
                target,
                user_override,
                sources=sources,
                peer_repos=peer_repos,
            )
        finally:
            self._user_override = None
            self._level_override = None

    def _collect_for_date_impl(  # noqa: C901
        self,
        target: date,
        user_override: dict | None = None,
        sources: list[str] | None = None,
        peer_repos: list[dict] | None = None,
    ) -> dict:
        year = target.year
        quarter = (target.month - 1) // 3 + 1
        quarter_starts = QUARTER_STARTS
        start_month, start_day = quarter_starts[quarter]
        quarter_start = date(year, start_month, start_day)
        day_of_quarter = (target - quarter_start).days + 1

        _src = set(sources) if sources else None

        events: list[dict] = []
        seen_ids: set[str] = set()
        target_str = target.isoformat()
        source_errors: dict[str, str] = {}
        sources_attempted: list[str] = []

        if not _src or "git" in _src:
            sources_attempted.append("git")
            git_author = (
                user_override["git_author"] if user_override else self.get_git_author()
            )
            git_authors = [git_author]
            if user_override:
                kerberos = user_override.get("username", "")
                if kerberos:
                    email = f"{kerberos}@redhat.com"
                    if email not in git_authors:
                        git_authors.append(email)
                gh_user = user_override.get("github_username", "")
                if gh_user and gh_user not in git_authors:
                    git_authors.append(gh_user)
                    noreply = f"{gh_user}@users.noreply.github.com"
                    git_authors.append(noreply)
                gl_user = user_override.get("gitlab_username", "")
                if gl_user and gl_user not in git_authors:
                    git_authors.append(gl_user)

                if not peer_repos:
                    peer_repo_paths: list[str] = []
                    gl_user = user_override.get("gitlab_username", "")
                    if gl_user:
                        gl_cache = self.get_gitlab_cache(
                            year, quarter, username_override=gl_user
                        )
                        for mr in gl_cache.get("mrs_authored", []):
                            p = mr.get("gitlab_path", "")
                            if p:
                                peer_repo_paths.append(p)
                    gh_user = user_override.get("github_username", "")
                    if gh_user:
                        gh_cache = self.get_github_cache(
                            year, quarter, username_override=gh_user
                        )
                        for pr in gh_cache.get("prs_authored", []):
                            repo = (pr.get("repository") or {}).get("nameWithOwner", "")
                            if repo:
                                peer_repo_paths.append(f"github:{repo}")
                    if peer_repo_paths:
                        unique = list(set(peer_repo_paths))
                        self.discover_peer_repos(unique[:10])

            if peer_repos is not None:
                repos = peer_repos
            else:
                repos = self.get_config_repos(include_cached=bool(user_override))
            for repo in repos:
                for author in git_authors:
                    try:
                        cmd = [
                            "git",
                            "-C",
                            repo["path"],
                            "log",
                            f"--since={target_str} 00:00:00",
                            f"--until={target_str} 23:59:59",
                            f"--author={author}",
                            "--format=%H|%s|%ad|%b%x00",
                            "--date=iso",
                        ]
                        cmd.append("--all")
                        output = subprocess.check_output(
                            cmd, text=True, stderr=subprocess.DEVNULL, timeout=15
                        )
                        for record in output.split("\x00"):
                            record = record.strip()
                            if not record:
                                continue
                            parts = record.split("|", 3)
                            if len(parts) < 2:
                                continue
                            sha = parts[0][:8]
                            message = parts[1]
                            ts = parts[2] if len(parts) > 2 else target_str
                            body = parts[3].strip()[:300] if len(parts) > 3 else ""
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
                            if body and body.lower() not in message.lower():
                                ev["extra_classification_text"] = body
                            events.append(self._enrich_event(ev))
                    except Exception as e:
                        err_msg = f"Git collect failed for {repo['name']} author={author}: {e}"
                        logger.warning(err_msg)
                        source_errors.setdefault("git", err_msg)

        if not _src or "jira" in _src:
            sources_attempted.append("jira")
            jira_user = user_override.get("jira_username", "") if user_override else ""
            jira_date = target.strftime("%Y-%m-%d")
            jira_next = (target + timedelta(days=1)).strftime("%Y-%m-%d")
            if user_override and jira_user:
                prefetched = self.prefetch_jira_quarter(jira_user, year, quarter)
                for ev in prefetched.get(target_str, []):
                    if ev["id"] not in seen_ids:
                        seen_ids.add(ev["id"])
                        events.append(self._enrich_event(ev))
            else:
                try:
                    if _circuit.is_open("jira"):
                        raise RuntimeError("circuit breaker open")
                    assignee_clause = (
                        "(assignee = currentUser() OR reporter = currentUser())"
                    )
                    jql = (
                        f"resolved >= '{jira_date}' AND resolved < '{jira_next}' "
                        f"AND {assignee_clause} "
                        f"ORDER BY resolved DESC"
                    )
                    ok, result = run_cmd_sync(
                        ["rh-issue", "search", jql, "--max-results", "50"],
                        timeout=30,
                    )
                    if not ok:
                        raise RuntimeError(result)
                    _circuit.record_success("jira")
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
                        jira_proj = _jira_project_from_key(key)
                        ev = {
                            "id": event_id,
                            "source": "jira",
                            "type": "issue_resolved",
                            "item_id": key,
                            "title": f"{key}: {summary}",
                            "timestamp": datetime.now().isoformat(),
                            "jira_project": jira_proj,
                            "is_cross_team": jira_proj not in ("AAP", "ANSTRAT"),
                        }
                        events.append(self._enrich_event(ev))
                except Exception as e:
                    _circuit.record_failure("jira")
                    err_msg = f"Jira resolved fetch failed: {e}"
                    logger.warning(err_msg)
                    source_errors.setdefault("jira", err_msg)

        if not _src or "github" in _src:
            sources_attempted.append("github")
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
                err_msg = f"GitHub collect failed: {e}"
                logger.warning(err_msg)
                source_errors["github"] = err_msg

        if not _src or "gitlab" in _src:
            sources_attempted.append("gitlab")
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
                err_msg = f"GitLab collect failed: {e}"
                logger.warning(err_msg)
                source_errors["gitlab"] = err_msg

        if not _src or "jira" in _src:
            jira_created_user = (
                user_override.get("jira_username", "") if user_override else ""
            )
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
                err_msg = f"Jira created collect failed: {e}"
                logger.warning(err_msg)
                source_errors.setdefault("jira", err_msg)

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
                err_msg = f"Session collect failed: {e}"
                logger.warning(err_msg)
                source_errors["session"] = err_msg

        if (not _src or "gdrive" in _src) and not user_override:
            sources_attempted.append("gdrive")
            try:
                if _circuit.is_open("gdrive"):
                    raise RuntimeError("circuit breaker open")
                perf_dir = self.get_perf_dir(target.year, (target.month - 1) // 3 + 1)
                gdrive_events = collect_gdrive_contributions(
                    perf_dir=perf_dir,
                    target=target,
                )
                added_gdrive = 0
                for ev in gdrive_events:
                    if ev.get("timestamp", "")[:10] != target_str:
                        continue
                    if ev["id"] not in seen_ids:
                        seen_ids.add(ev["id"])
                        events.append(self._enrich_event(ev))
                        added_gdrive += 1
                if added_gdrive:
                    logger.info(
                        f"GDrive: collected {added_gdrive} events for {target_str}"
                    )

                try:
                    cfg = get_merged_config()
                    my_email = cfg.get("user_email", "")
                    if not my_email:
                        my_email = subprocess.check_output(
                            ["git", "config", "user.email"],
                            text=True,
                        ).strip()
                    if my_email:
                        shared_events = collect_shared_drive_peer_contributions(
                            perf_dir=perf_dir,
                            peer_email=my_email,
                            target=target,
                        )
                        added = 0
                        for ev in shared_events:
                            if ev.get("timestamp", "")[:10] != target_str:
                                continue
                            if ev["id"] not in seen_ids:
                                seen_ids.add(ev["id"])
                                events.append(self._enrich_event(ev))
                                added += 1
                        if added:
                            logger.info(
                                f"GDrive shared (self): added {added} extra events "
                                f"for {target_str}"
                            )
                except Exception as e:
                    logger.warning("GDrive shared self-enrichment failed: %s", e)

                _circuit.record_success("gdrive")
            except Exception as e:
                _circuit.record_failure("gdrive")
                err_msg = f"GDrive collect failed: {e}"
                logger.warning(err_msg)
                source_errors["gdrive"] = err_msg

        if (not _src or "gdrive" in _src) and user_override:
            try:
                if _circuit.is_open("gdrive_shared"):
                    raise RuntimeError("circuit breaker open for gdrive_shared")
                peer_email = user_override.get("email", "")
                if not peer_email:
                    kerberos = user_override.get("username", "")
                    if kerberos:
                        peer_email = f"{kerberos}@redhat.com"
                if peer_email:
                    perf_dir = self.get_perf_dir(
                        target.year, (target.month - 1) // 3 + 1
                    )
                    shared_events = collect_shared_drive_peer_contributions(
                        perf_dir=perf_dir,
                        peer_email=peer_email,
                        target=target,
                    )
                    added_shared = 0
                    for ev in shared_events:
                        if ev.get("timestamp", "")[:10] != target_str:
                            continue
                        if ev["id"] not in seen_ids:
                            seen_ids.add(ev["id"])
                            events.append(self._enrich_event(ev))
                            added_shared += 1
                    if added_shared:
                        logger.info(
                            f"GDrive shared: collected {added_shared} events "
                            f"for peer {peer_email} on {target_str}"
                        )
                _circuit.record_success("gdrive_shared")
            except Exception as e:
                _circuit.record_failure("gdrive_shared")
                err_msg = f"GDrive shared collect failed: {e}"
                logger.warning(err_msg)
                source_errors["gdrive_shared"] = err_msg

        if (not _src or "meeting" in _src) and not user_override:
            sources_attempted.append("meeting")
            try:
                if _circuit.is_open("meeting"):
                    raise RuntimeError("circuit breaker open")
                perf_dir = self.get_perf_dir(target.year, (target.month - 1) // 3 + 1)
                meeting_events = collect_meeting_contributions(
                    perf_dir=perf_dir,
                    target=target,
                )
                added_meetings = 0
                for ev in meeting_events:
                    if ev.get("timestamp", "")[:10] != target_str:
                        continue
                    if ev["id"] not in seen_ids:
                        seen_ids.add(ev["id"])
                        events.append(self._enrich_event(ev))
                        added_meetings += 1
                if added_meetings:
                    logger.info(
                        f"Meetings: collected {added_meetings} events for {target_str}"
                    )
                _circuit.record_success("meeting")
            except Exception as e:
                _circuit.record_failure("meeting")
                err_msg = f"Meeting collect failed: {e}"
                logger.warning(err_msg)
                source_errors["meeting"] = err_msg

        if (not _src or "meeting" in _src) and user_override:
            try:
                if _circuit.is_open("meeting_peer"):
                    raise RuntimeError("circuit breaker open for meeting_peer")
                peer_email = user_override.get("email", "")
                if not peer_email:
                    kerberos = user_override.get("username", "")
                    if kerberos:
                        peer_email = f"{kerberos}@redhat.com"
                if peer_email:
                    perf_dir = self.get_perf_dir(
                        target.year, (target.month - 1) // 3 + 1
                    )
                    peer_mtg_events = collect_meeting_peer_contributions(
                        perf_dir=perf_dir,
                        peer_email=peer_email,
                        target=target,
                    )
                    added_peer_mtg = 0
                    for ev in peer_mtg_events:
                        if ev.get("timestamp", "")[:10] != target_str:
                            continue
                        if ev["id"] not in seen_ids:
                            seen_ids.add(ev["id"])
                            events.append(self._enrich_event(ev))
                            added_peer_mtg += 1
                    if added_peer_mtg:
                        logger.info(
                            f"Meeting peer: collected {added_peer_mtg} events "
                            f"for peer {peer_email} on {target_str}"
                        )
                _circuit.record_success("meeting_peer")
            except Exception as e:
                _circuit.record_failure("meeting_peer")
                err_msg = f"Meeting peer collect failed: {e}"
                logger.warning(err_msg)
                source_errors["meeting_peer"] = err_msg

        if user_override and events:
            new_keys = self._fetch_missing_hierarchy(events)
            if new_keys:
                events = self._re_enrich_events(events)

        if user_override:
            peer_name = user_override.get("username", "unknown")
            peer_dir = self.get_perf_dir(year, quarter) / "peers" / peer_name / "daily"
            peer_dir.mkdir(parents=True, exist_ok=True)
            daily_file = peer_dir / f"{target_str}.json"
        else:
            daily_dir = self.get_daily_dir(year, quarter)
            daily_dir.mkdir(parents=True, exist_ok=True)
            daily_file = daily_dir / f"{target_str}.json"

        if _src and daily_file.exists():
            try:
                with open(daily_file, encoding="utf-8") as f:
                    existing = json.load(f)
                kept = [
                    e for e in existing.get("events", []) if e.get("source") not in _src
                ]
                new_ids = {e["id"] for e in events}
                kept = [e for e in kept if e["id"] not in new_ids]
                events = kept + events
            except Exception as e:
                logger.error(
                    "Failed to merge with existing daily file %s (events from other "
                    "sources may be lost): %s",
                    daily_file,
                    e,
                )

        _, _, daily_cap, _ = get_effective_defs()
        daily_points: dict[str, int] = {}
        for event in events:
            for comp_id, pts in event.get("points", {}).items():
                current = daily_points.get(comp_id, 0)
                daily_points[comp_id] = min(current + pts, daily_cap)

        sources_succeeded = [s for s in sources_attempted if s not in source_errors]
        if source_errors:
            logger.warning(
                "Collection for %s had %d source failure(s): %s",
                target_str,
                len(source_errors),
                ", ".join(f"{k}: {v}" for k, v in source_errors.items()),
            )

        daily_data = {
            "date": target_str,
            "day_of_quarter": day_of_quarter,
            "events": events,
            "daily_points": daily_points,
            "daily_total": sum(daily_points.values()),
            "saved_at": datetime.now().isoformat(),
            "sources_attempted": sources_attempted,
            "sources_succeeded": sources_succeeded,
            "source_errors": source_errors,
        }

        with open(daily_file, "w", encoding="utf-8") as f:
            json.dump(daily_data, f, indent=2)

        return daily_data
