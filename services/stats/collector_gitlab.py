"""GitLab MR and review collection mixin for DataCollector."""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

from services.stats.quarter_utils import QUARTER_STARTS

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SHORT = 15
PAGE_SIZE = 100
MR_NOTES_FETCH_LIMIT = 15
GITLAB_MEM_TTL = 3600
GITLAB_DISK_TTL = 86400
TRUNCATE_CONTEXT = 200


@dataclass
class GitlabFetchContext:
    cfg: dict
    gitlab_host: str
    token: str
    username: str
    q_start: str
    q_end: str
    mrs_authored: list[dict]
    reviews_given: list[dict]
    reviews_received: list[dict]
    seen: set[str]


__all__ = ["GitLabCollectorMixin", "GitlabFetchContext"]


class GitLabCollectorMixin:
    """Mixin providing GitLab MR and review collection for DataCollector."""

    _gitlab_mem_cache: dict[str, tuple[float, dict]] = {}
    _gitlab_mem_lock = threading.Lock()

    def _get_gitlab_token(self) -> str:
        """Load GitLab private token from env or glab-cli config."""
        token = os.environ.get("GITLAB_TOKEN", "")
        if token:
            return token
        glab_config = Path.home() / ".config" / "glab-cli" / "config.yml"
        if glab_config.exists():
            try:
                with open(glab_config, encoding="utf-8") as fh:
                    gc = yaml.safe_load(fh)
                for host_data in gc.get("hosts", {}).values():
                    t = host_data.get("token", "")
                    if t:
                        return t
            except (OSError, yaml.YAMLError) as e:
                logger.warning("Failed to read GitLab token from glab config: %s", e)
        return ""

    def _get_gitlab_username(self, host: str, token: str) -> str:
        """Resolve the current GitLab username via API."""
        try:
            url = f"https://{host}/api/v4/user"
            req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read()).get("username", "")
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
            logger.warning("GitLab API /user failed for %s: %s", host, e)
            return ""

    def _gitlab_api_get(self, host: str, token: str, path: str) -> list | dict:
        """Make a GET request to GitLab API, returning parsed JSON."""
        url = f"https://{host}/api/v4/{path}"
        req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SHORT) as resp:
            return json.loads(resp.read())

    def get_gitlab_cache(
        self, year: int, quarter: int, username_override: str = ""
    ) -> dict:
        """Fetch GitLab MRs and review activity for the quarter, with caching."""
        perf_dir = self.get_perf_dir(year, quarter)
        cache_suffix = f"_{username_override}" if username_override else ""
        cache_file = perf_dir / f"gitlab_event_cache{cache_suffix}.json"
        mem_key = str(cache_file)

        with self._gitlab_mem_lock:
            if mem_key in self._gitlab_mem_cache:
                ts, data = self._gitlab_mem_cache[mem_key]
                if time.time() - ts < GITLAB_MEM_TTL:
                    return data

        if cache_file.exists():
            try:
                mtime = cache_file.stat().st_mtime
                if time.time() - mtime < GITLAB_DISK_TTL:
                    with open(cache_file, encoding="utf-8") as f:
                        cached = json.load(f)
                    if cached.get("mrs_authored") or not username_override:
                        with self._gitlab_mem_lock:
                            self._gitlab_mem_cache[mem_key] = (time.time(), cached)
                        return cached
            except (json.JSONDecodeError, OSError) as e:
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
                GitlabFetchContext(
                    cfg=cfg,
                    gitlab_host=gitlab_host,
                    token=token,
                    username=username,
                    q_start=q_start,
                    q_end=q_end,
                    mrs_authored=mrs_authored,
                    reviews_given=reviews_given,
                    reviews_received=reviews_received,
                    seen=seen,
                )
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
            except OSError as e:
                logger.warning("Failed to save GitLab cache: %s", e)

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
                    "description": (mr.get("description") or "")[:TRUNCATE_CONTEXT],
                }
            )

        endpoints = [
            (
                f"merge_requests?scope=all&author_username={username}"
                f"&created_after={q_start}&created_before={q_end}"
                f"&per_page={PAGE_SIZE}"
            ),
            (
                f"merge_requests?scope=all&author_username={username}"
                f"&state=merged&updated_after={q_start}&updated_before={q_end}"
                f"&per_page={PAGE_SIZE}"
            ),
            (
                f"merge_requests?scope=all&author_username={username}"
                f"&state=opened&updated_after={q_start}"
                f"&per_page={PAGE_SIZE}"
            ),
            (
                f"merge_requests?scope=all&author_username={username}"
                f"&state=closed&updated_after={q_start}&updated_before={q_end}"
                f"&per_page={PAGE_SIZE}"
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
                    if len(batch) < PAGE_SIZE:
                        break
                    page += 1
                except (
                    OSError,
                    json.JSONDecodeError,
                    KeyError,
                    ValueError,
                    TypeError,
                ) as e:
                    logger.info("GitLab global MR fetch for %s: %s", username, e)
                    break

        for mr_data in mrs_authored[:MR_NOTES_FETCH_LIMIT]:
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
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                ValueError,
                TypeError,
            ) as e:
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
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                ValueError,
                TypeError,
            ) as e:
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

    def _fetch_gitlab_per_repo(self, ctx: GitlabFetchContext) -> dict:
        """Fetch GitLab MRs by iterating configured repos (for the current user)."""
        repos = ctx.cfg.get("repositories", {})

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
                    if uid in ctx.seen:
                        continue
                    ctx.seen.add(uid)
                    ctx.mrs_authored.append(
                        {
                            "project": _repo,
                            "gitlab_path": _gl_path,
                            "iid": mr["iid"],
                            "title": mr.get("title", ""),
                            "state": mr.get("state", ""),
                            "web_url": mr.get("web_url", ""),
                            "created_at": mr.get("created_at", ""),
                            "merged_at": mr.get("merged_at") or "",
                            "description": (mr.get("description") or "")[
                                :TRUNCATE_CONTEXT
                            ],
                        }
                    )

            try:
                _add_authored(
                    self._gitlab_api_get(
                        ctx.gitlab_host,
                        ctx.token,
                        f"projects/{encoded}/merge_requests"
                        f"?scope=all&author_username={ctx.username}"
                        f"&created_after={ctx.q_start}&created_before={ctx.q_end}&per_page=100",
                    )
                )
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                ValueError,
                TypeError,
            ) as e:
                logger.debug("GitLab MR fetch (created) for %s: %s", repo_name, e)

            try:
                _add_authored(
                    self._gitlab_api_get(
                        ctx.gitlab_host,
                        ctx.token,
                        f"projects/{encoded}/merge_requests"
                        f"?scope=all&author_username={ctx.username}"
                        f"&state=opened&per_page=100",
                    )
                )
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                ValueError,
                TypeError,
            ) as e:
                logger.debug("GitLab MR fetch (open) for %s: %s", repo_name, e)

            try:
                _add_authored(
                    self._gitlab_api_get(
                        ctx.gitlab_host,
                        ctx.token,
                        f"projects/{encoded}/merge_requests"
                        f"?scope=all&author_username={ctx.username}"
                        f"&state=merged&updated_after={ctx.q_start}&updated_before={ctx.q_end}"
                        f"&per_page={PAGE_SIZE}",
                    )
                )
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                ValueError,
                TypeError,
            ) as e:
                logger.debug("GitLab MR fetch (merged) for %s: %s", repo_name, e)

            try:
                recent_mrs = self._gitlab_api_get(
                    ctx.gitlab_host,
                    ctx.token,
                    f"projects/{encoded}/merge_requests"
                    f"?scope=all&updated_after={ctx.q_start}&per_page=50&state=all",
                )
                for mr in recent_mrs:
                    mr_author = (mr.get("author", {}) or {}).get("username", "")
                    iid = mr["iid"]
                    try:
                        notes = self._gitlab_api_get(
                            ctx.gitlab_host,
                            ctx.token,
                            f"projects/{encoded}/merge_requests/{iid}/notes"
                            f"?per_page=100&sort=desc",
                        )
                    except (
                        OSError,
                        json.JSONDecodeError,
                        KeyError,
                        ValueError,
                        TypeError,
                    ) as e:
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
                        note_body = (note.get("body") or "")[:TRUNCATE_CONTEXT]
                        note_id = note.get("id", "")

                        if note_author == ctx.username and mr_author != ctx.username:
                            ctx.reviews_given.append(
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
                        elif note_author != ctx.username and mr_author == ctx.username:
                            ctx.reviews_received.append(
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
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                ValueError,
                TypeError,
            ) as e:
                logger.debug("GitLab review fetch for %s: %s", repo_name, e)

        return {
            "mrs_authored": ctx.mrs_authored,
            "reviews_given": ctx.reviews_given,
            "reviews_received": ctx.reviews_received,
        }

    def collect_gitlab_for_date(
        self, target, seen_ids: set[str], username_override: str = ""
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
                ev["extra_classification_text"] = (
                    f"review comment: {note_body[:TRUNCATE_CONTEXT]}"
                )
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
                ev["extra_classification_text"] = (
                    f"review comment: {note_body[:TRUNCATE_CONTEXT]}"
                )
            events.append(self._enrich_event(ev))

        return events
