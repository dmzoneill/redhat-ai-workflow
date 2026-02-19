import json
import logging
import os
import re
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from server.paths import AA_CONFIG_DIR, PERFORMANCE_DIR
from services.stats.email_parser import collect_executive_emails_for_date
from services.stats.scorer import get_effective_defs, map_competencies

logger = logging.getLogger(__name__)


class DataCollector:
    def __init__(self):
        self._git_author_cache: str | None = None
        self._github_username_cache: str | None = None

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

    def get_github_cache(self, year: int, quarter: int) -> dict:
        perf_dir = self.get_perf_dir(year, quarter)
        cache_file = perf_dir / "github_cache.json"

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

        username = self.get_github_username()
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

    def collect_github_for_date(self, target: date, seen_ids: set[str]) -> list[dict]:
        year = target.year
        quarter = (target.month - 1) // 3 + 1
        target_str = target.isoformat()
        events: list[dict] = []

        cache = self.get_github_cache(year, quarter)

        def _parse_date(iso_str: str | None) -> str | None:
            if not iso_str:
                return None
            return iso_str[:10]

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
                    ev_title = f"[{repo}] PR #{number} merged: {title}"
                    events.append(
                        {
                            "id": event_id,
                            "source": "github",
                            "type": "pr_merged",
                            "item_id": f"{repo}#{number}",
                            "title": ev_title,
                            "url": url,
                            "timestamp": closed_raw or target_str,
                            "points": map_competencies(ev_title, "github", "pr_merged"),
                        }
                    )
            elif created == target_str:
                event_id = f"gh-{repo}-pr-{number}-opened"
                if event_id not in seen_ids:
                    seen_ids.add(event_id)
                    ev_title = f"[{repo}] PR #{number} opened: {title}"
                    events.append(
                        {
                            "id": event_id,
                            "source": "github",
                            "type": "pr_opened",
                            "item_id": f"{repo}#{number}",
                            "title": ev_title,
                            "url": url,
                            "timestamp": pr.get("createdAt", target_str),
                            "points": map_competencies(ev_title, "github", "pr_opened"),
                        }
                    )

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
                    ev_title = f"[{repo}] Reviewed PR #{number}: {title}"
                    events.append(
                        {
                            "id": event_id,
                            "source": "github",
                            "type": "pr_reviewed",
                            "item_id": f"{repo}#{number}",
                            "title": ev_title,
                            "url": url,
                            "timestamp": pr.get("createdAt", target_str),
                            "points": map_competencies(
                                ev_title, "github", "pr_reviewed"
                            ),
                        }
                    )

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
                    ev_title = f"[{repo}] Issue #{number} closed: {title}"
                    events.append(
                        {
                            "id": event_id,
                            "source": "github",
                            "type": "issue_closed",
                            "item_id": f"{repo}#{number}",
                            "title": ev_title,
                            "url": url,
                            "timestamp": issue.get("closedAt", target_str),
                            "points": map_competencies(
                                ev_title, "github", "issue_closed"
                            ),
                        }
                    )
            elif created == target_str:
                event_id = f"gh-{repo}-issue-{number}-opened"
                if event_id not in seen_ids:
                    seen_ids.add(event_id)
                    ev_title = f"[{repo}] Issue #{number} opened: {title}"
                    events.append(
                        {
                            "id": event_id,
                            "source": "github",
                            "type": "issue_opened",
                            "item_id": f"{repo}#{number}",
                            "title": ev_title,
                            "url": url,
                            "timestamp": issue.get("createdAt", target_str),
                            "points": map_competencies(
                                ev_title, "github", "issue_opened"
                            ),
                        }
                    )

        return events

    def collect_for_date(self, target: date) -> dict:
        year = target.year
        quarter = (target.month - 1) // 3 + 1
        quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        start_month, start_day = quarter_starts[quarter]
        quarter_start = date(year, start_month, start_day)
        day_of_quarter = (target - quarter_start).days + 1

        events: list[dict] = []
        seen_ids: set[str] = set()
        target_str = target.isoformat()

        git_author = self.get_git_author()
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
                    events.append(
                        {
                            "id": event_id,
                            "source": "git",
                            "type": "commit",
                            "item_id": sha,
                            "title": title,
                            "timestamp": ts,
                            "points": map_competencies(title, "git", "commit"),
                        }
                    )
            except Exception as e:
                logger.debug(f"Git collect failed for {repo['name']}: {e}")

        jira_date = target.strftime("%Y-%m-%d")
        try:
            jql = (
                f"resolved >= '{jira_date}' AND resolved < '{jira_date}' + 1d "
                f"AND (assignee = currentUser() OR reporter = currentUser()) "
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
                events.append(
                    {
                        "id": event_id,
                        "source": "jira",
                        "type": "issue_resolved",
                        "item_id": key,
                        "title": title,
                        "timestamp": datetime.now().isoformat(),
                        "points": map_competencies(title, "jira", "issue_resolved"),
                    }
                )
        except Exception as e:
            logger.debug(f"Jira resolved fetch failed: {e}")

        try:
            gh_events = self.collect_github_for_date(target, seen_ids)
            events.extend(gh_events)
            if gh_events:
                logger.info(
                    f"GitHub: collected {len(gh_events)} events for {target_str}"
                )
        except Exception as e:
            logger.debug(f"GitHub collect failed: {e}")

        try:
            perf_dir = self.get_perf_dir(target.year, (target.month - 1) // 3 + 1)
            new_email_ids = collect_executive_emails_for_date(target, perf_dir)
            if new_email_ids:
                logger.info(
                    f"Gmail: cached {len(new_email_ids)} executive emails for {target_str}"
                )
        except Exception as e:
            logger.warning(f"Executive email collect failed (non-blocking): {e}")

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

        daily_dir = self.get_daily_dir(year, quarter)
        daily_dir.mkdir(parents=True, exist_ok=True)
        daily_file = daily_dir / f"{target_str}.json"
        with open(daily_file, "w", encoding="utf-8") as f:
            json.dump(daily_data, f, indent=2)

        return daily_data
