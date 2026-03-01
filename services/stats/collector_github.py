"""GitHub PR and issue collection mixin for DataCollector."""

import json
import logging
import subprocess
import threading
import time
from datetime import date, timedelta

from services.stats.quarter_utils import QUARTER_STARTS

logger = logging.getLogger(__name__)

__all__ = ["GitHubCollectorMixin"]


class GitHubCollectorMixin:
    """Mixin providing GitHub PR and issue collection for DataCollector."""

    _github_mem_cache: dict[str, tuple[float, dict]] = {}
    _github_mem_lock = threading.Lock()

    def _get_github_repo_metadata(self, year: int, quarter: int) -> dict:
        """Load or build a cache of GitHub repo fork/org metadata."""
        perf_dir = self.get_perf_dir(year, quarter)
        cache_file = perf_dir / "github_repo_metadata.json"
        if cache_file.exists():
            try:
                with open(cache_file, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
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
        except OSError as e:
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
        except (subprocess.SubprocessError, OSError) as e:
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
            except (json.JSONDecodeError, OSError) as e:
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
            except OSError as e:
                logger.warning("Failed to save GitHub cache: %s", e)

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
            except (
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
                FileNotFoundError,
                json.JSONDecodeError,
            ) as e:
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
                logger.info("GitHub %s: fetched %d results", key, len(results))
            except (
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
                FileNotFoundError,
                json.JSONDecodeError,
            ) as e:
                logger.warning("GitHub search failed for %s: %s", key, e)
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
