"""Executive-email D-Bus handlers for the stats daemon.

Split out of ``services/stats/daemon.py``; ``StatsDaemon`` mixes
``ExecutiveEmailMixin`` in, so the handler names and D-Bus methods are
unchanged.
"""

import asyncio
import functools
import hashlib
import importlib
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from services.stats.email_parser import get_executive_senders, parse_email_text
from services.stats.handler_utils import (
    decode_b64,
    html_to_text,
    now_local,
    quarter_of,
    quarter_start,
    read_json,
    today_local,
    write_json,
)
from services.stats.issue_hierarchy import IssueHierarchyMixin

logger = logging.getLogger(__name__)

_GMAIL_MODULE = "tool_modules.aa_gmail.src.tools_basic"
_GMAIL_UNAVAILABLE = "Gmail module not available"
_BODY_LIMIT = 10000


def gmail_service() -> tuple[Any, str | None]:
    """Return ``(service, error)``; the Gmail tool module is optional."""
    try:
        module = importlib.import_module(_GMAIL_MODULE)
    except ImportError:
        return None, _GMAIL_UNAVAILABLE
    service, error = module.get_gmail_service()
    return service, error


@functools.cache
def gmail_errors() -> tuple[type[Exception], ...]:
    """Exceptions a Gmail API call can raise (network, auth, API and data errors)."""
    errors: list[type[Exception]] = [OSError, ValueError, KeyError, TypeError]
    for module_name, attr in (
        ("googleapiclient.errors", "Error"),
        ("google.auth.exceptions", "GoogleAuthError"),
        ("httplib2", "HttpLib2Error"),
    ):
        try:
            errors.append(getattr(importlib.import_module(module_name), attr))
        except (ImportError, AttributeError):
            continue
    return tuple(errors)


def header_map(payload: dict) -> dict[str, str]:
    """Gmail message headers as ``{name: value}``."""
    return {h["name"]: h["value"] for h in payload.get("headers", [])}


def flat_message_body(payload: dict) -> str:
    """Body of a message: first text/plain part, else first text/html part, else the payload body."""
    parts = payload.get("parts", [])
    for mime in ("text/plain", "text/html"):
        for part in parts:
            data = part.get("body", {}).get("data", "")
            if part.get("mimeType") == mime and data:
                text = decode_b64(data)
                return text if mime == "text/plain" else html_to_text(text)
    data = payload.get("body", {}).get("data", "")
    return decode_b64(data) if data else ""


def nested_message_body(part: dict) -> str:
    """Depth-first body of a (possibly multipart) message part."""
    mime = part.get("mimeType", "")
    data = part.get("body", {}).get("data", "")
    if mime == "text/plain" and data:
        return decode_b64(data)
    if mime == "text/html" and data:
        return html_to_text(decode_b64(data))
    for sub_part in part.get("parts", []):
        text = nested_message_body(sub_part)
        if text:
            return text
    return ""


def collect_issues(nodes: Any, user_issues: dict[str, dict], parent_anstrat: str = "") -> None:
    """Flatten a hierarchy tree into ``user_issues`` keyed by issue key."""
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
        anstrat = key if key.startswith("ANSTRAT-") else parent_anstrat
        collect_issues(node.get("children", []), user_issues, anstrat)


_CONFIDENCE = {"direct_key": "high", "anstrat_link": "high", "theme": "medium"}


def _mapping(match_type: str, issue_key: str, info: dict, context: str, priority: str) -> dict:
    return {
        "match_type": match_type,
        "confidence": _CONFIDENCE[match_type],
        "user_issue": issue_key,
        "user_summary": info.get("summary", ""),
        "user_points": info.get("points", 0),
        "email_context": context,
        "priority_name": priority,
    }


def _first_context(email_keys: dict[str, list], key: str, default: str) -> str:
    contexts = email_keys.get(key, [])
    return contexts[0] if contexts else default


def direct_mappings(email_keys: dict[str, list], user_issues: dict[str, dict]) -> list[dict]:
    """User issues the email names by key."""
    return [
        _mapping("direct_key", key, user_issues[key], _first_context(email_keys, key, ""), "")
        for key in sorted(set(email_keys) & set(user_issues))
    ]


def anstrat_mappings(email_keys: dict[str, list], user_issues: dict[str, dict], skip: set[str]) -> list[dict]:
    """User issues whose parent ANSTRAT the email names."""
    email_anstrats = {k for k in email_keys if k.startswith("ANSTRAT-")}
    mappings = []
    for issue_key, info in user_issues.items():
        parent = info.get("parent_anstrat", "")
        if issue_key in skip or not parent or parent not in email_anstrats:
            continue
        context = _first_context(email_keys, parent, f"Under {parent}")
        mappings.append(_mapping("anstrat_link", issue_key, info, context, parent))
    return mappings


def theme_mappings(themes: list[dict], user_issues: dict[str, dict], skip: set[str]) -> list[dict]:
    """First email theme sharing a keyword with each still-unmapped user issue."""
    mappings = []
    for issue_key, info in user_issues.items():
        user_kws = set(info.get("keywords", []))
        if issue_key in skip or not user_kws:
            continue
        for theme in themes:
            overlap = user_kws & set(theme.get("matched_keywords", []))
            if overlap:
                context = f"Theme: {theme['name']} (keywords: {', '.join(overlap)})"
                mappings.append(_mapping("theme", issue_key, info, context, theme["name"]))
                break
    return mappings


def map_issues_to_email(parsed: dict, user_issues: dict[str, dict]) -> list[dict]:
    """Match the user's issues to the email by key, by ANSTRAT parent, then by theme."""
    email_keys: dict[str, list] = parsed.get("issue_keys", {})
    mappings = direct_mappings(email_keys, user_issues)
    mappings += anstrat_mappings(email_keys, user_issues, {m["user_issue"] for m in mappings})
    mappings += theme_mappings(parsed.get("themes", []), user_issues, {m["user_issue"] for m in mappings})
    return mappings


def priority_coverage(parsed: dict, mappings: list[dict], user_issues: dict[str, dict]) -> list[dict]:
    """Whether each priority in the email is covered by the user's mapped issues."""
    coverage: list[dict] = []
    for prio in parsed.get("priorities", []):
        prio_keys = set(prio.get("issue_keys", []))
        prio_name = prio.get("name", "")
        matching = [
            m
            for m in mappings
            if m.get("priority_name") == prio_name
            or m["user_issue"] in prio_keys
            or (m.get("priority_name", "").startswith("ANSTRAT-") and m["priority_name"] in prio_keys)
        ]
        direct = prio_keys & set(user_issues)
        coverage.append(
            {
                "name": prio_name,
                "context": prio.get("context", "")[:150],
                "issue_keys": list(prio_keys),
                "status": "covered" if (matching or direct) else "gap",
                "matching_issues": [m["user_issue"] for m in matching] + list(direct),
            }
        )
    return coverage


def latest_email_file(emails_dir: Path) -> Path | None:
    """Most recently modified cached email, if any."""
    if not emails_dir.exists():
        return None
    files = sorted(emails_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def list_email_summaries(emails_dir: Path) -> list[dict]:
    """Summaries of the cached emails, newest first; unreadable files are skipped."""
    if not emails_dir.exists():
        return []
    emails: list[dict] = []
    for path in sorted(emails_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = read_json(path)
        except (OSError, ValueError):
            continue
        emails.append(
            {
                "email_id": data.get("email_id", path.stem),
                "sender": data.get("sender", "Unknown"),
                "parsed_at": data.get("parsed_at", ""),
                "text_preview": data.get("text_preview", "")[:150],
                "total_priorities": data.get("total_priorities", 0),
                "total_issue_keys": data.get("total_issue_keys", 0),
                "total_themes": data.get("total_themes", 0),
            }
        )
    return emails


def existing_gmail_ids(emails_dir: Path) -> set[str]:
    """Gmail message IDs already cached in *emails_dir*."""
    ids: set[str] = set()
    for path in emails_dir.glob("*.json"):
        try:
            ids.add(read_json(path).get("gmail_message_id", ""))
        except (OSError, ValueError, AttributeError):
            continue
    return ids


def backfill_window(today: date, year: int, quarter: int) -> tuple[date, date]:
    """Gmail ``after:``/``before:`` dates covering the quarter up to today."""
    if quarter == 4:
        next_quarter_start = date(year + 1, 1, 1)
    else:
        next_quarter_start = quarter_start(year, quarter + 1)
    return quarter_start(year, quarter), min(today + timedelta(days=1), next_quarter_start)


class GmailBackfill:
    """Fetch and cache one quarter of emails from each executive sender."""

    def __init__(self, service: Any, emails_dir: Path, window: tuple[date, date]):
        self.service = service
        self.emails_dir = emails_dir
        self.window = window
        self.seen = existing_gmail_ids(emails_dir)
        self.collected_date = today_local().isoformat()
        self.totals = {"new": 0, "skipped": 0}
        self.sender_results: list[dict] = []

    def _list_messages(self, query: str) -> list[dict]:
        messages: list[dict] = []
        page_token = None
        while True:
            request: dict = {"userId": "me", "q": query, "maxResults": 100}
            if page_token:
                request["pageToken"] = page_token
            results = self.service.users().messages().list(**request).execute()
            messages.extend(results.get("messages", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                return messages

    def _cache_message(self, sender: str, mid: str) -> bool:
        msg_data = self.service.users().messages().get(userId="me", id=mid, format="full").execute()
        payload = msg_data.get("payload", {})
        headers = header_map(payload)
        body = nested_message_body(payload)
        if not body:
            logger.warning("Skipping email from %s (mid=%s): no extractable body", sender, mid[:8])
            return False

        parsed = parse_email_text(body[:_BODY_LIMIT])
        eid = hashlib.sha256(f"{mid}:{sender}".encode()).hexdigest()[:12]
        parsed.update(
            {
                "email_id": eid,
                "gmail_message_id": mid,
                "sender": headers.get("From", sender),
                "sender_email": sender,
                "subject": headers.get("Subject", ""),
                "email_date": headers.get("Date", ""),
                "collected_date": self.collected_date,
                "parsed_at": now_local().isoformat(),
                "text_preview": body[:300].replace("\n", " "),
            }
        )
        write_json(self.emails_dir / f"{eid}.json", parsed)
        self.seen.add(mid)
        logger.info("Backfill: cached email from %s: %s", sender, parsed.get("subject", "")[:60])
        return True

    def backfill_sender(self, sender: str) -> dict:
        """Cache every new email from *sender* in the window; return the sender's counts."""
        after, before = self.window
        query = f"from:{sender} after:{after.isoformat()} before:{before.isoformat()}"
        messages = self._list_messages(query)
        new = skipped = 0
        for msg in messages:
            if msg["id"] in self.seen:
                skipped += 1
            elif self._cache_message(sender, msg["id"]):
                new += 1
        self.totals["new"] += new
        self.totals["skipped"] += skipped
        return {"sender": sender, "found": len(messages), "new": new, "skipped": skipped}

    def run(self, senders: list[str]) -> None:
        """Backfill every sender; one sender's failure does not stop the others."""
        for sender in senders:
            try:
                self.sender_results.append(self.backfill_sender(sender))
            except gmail_errors() as e:
                logger.error("Backfill failed for %s: %s", sender, e)
                self.sender_results.append({"sender": sender, "error": str(e)})


class ExecutiveEmailMixin(IssueHierarchyMixin):
    """Parse, store, search and map executive strategy emails."""

    async def _handle_parse_executive_email(self, **kwargs) -> dict:
        """Parse an executive email and cache the result."""
        text = kwargs.get("text", "")
        email_id = kwargs.get("email_id", "")

        if not text:
            return {"success": False, "error": "No email text provided"}

        parsed = parse_email_text(text)
        if not email_id:
            email_id = hashlib.sha256(text[:500].encode()).hexdigest()[:12]

        parsed["email_id"] = email_id
        parsed["parsed_at"] = now_local().isoformat()
        parsed["text_preview"] = text[:300].replace("\n", " ")

        emails_dir = self.executive_emails_dir()
        emails_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(write_json, emails_dir / f"{email_id}.json", parsed)
        return {"success": True, **parsed}

    async def _handle_map_deliverables(self, **kwargs) -> dict:
        """Map user's delivered issues to executive email targets."""
        return await self.map_deliverables(kwargs.get("email_id", ""))

    async def map_deliverables(self, email_id: str = "") -> dict:
        """Map this quarter's issues to a cached email (default: the newest)."""

        emails_dir = self.executive_emails_dir()
        if email_id:
            cache_file = emails_dir / f"{email_id}.json"
            if not cache_file.exists():
                return {"success": False, "error": f"Email {email_id} not found"}
            parsed = await asyncio.to_thread(read_json, cache_file)
        else:
            latest = await asyncio.to_thread(latest_email_file, emails_dir)
            if latest is None:
                return {"success": False, "error": "No executive emails cached"}
            parsed = await asyncio.to_thread(read_json, latest)
            email_id = parsed.get("email_id", latest.stem)

        hierarchy_result = await self.issue_hierarchy(refresh=False)
        user_issues: dict[str, dict] = {}
        for section in ("strategies", "unattached_epics", "uncategorized"):
            collect_issues(hierarchy_result.get(section, []), user_issues)

        mappings = map_issues_to_email(parsed, user_issues)
        coverage = priority_coverage(parsed, mappings, user_issues)
        mapped_keys = {m["user_issue"] for m in mappings}
        covered = sum(1 for p in coverage if p["status"] == "covered")
        total_priorities = len(coverage)

        return {
            "success": True,
            "email_id": email_id,
            "mappings": mappings,
            "priority_coverage": coverage,
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
                kind: sum(1 for m in mappings if m["match_type"] == kind)
                for kind in ("direct_key", "anstrat_link", "theme")
            },
        }

    async def _handle_list_executive_emails(self, **_kwargs) -> dict:
        """List cached parsed executive emails for the quarter."""
        return {"success": True, "emails": await self.list_executive_emails()}

    async def list_executive_emails(self) -> list[dict]:
        """Summaries of this quarter's cached executive emails, newest first."""
        return await asyncio.to_thread(list_email_summaries, self.executive_emails_dir())

    async def _handle_delete_executive_email(self, **kwargs) -> dict:
        """Delete a cached executive email."""
        email_id = kwargs.get("email_id", "")
        if not email_id:
            return {"success": False, "error": "No email_id provided"}

        cache_file = self.executive_emails_dir() / f"{email_id}.json"
        if cache_file.exists():
            cache_file.unlink()
            return {"success": True, "deleted": email_id}
        return {"success": False, "error": f"Email {email_id} not found"}

    async def _handle_search_executive_gmail(self, **kwargs) -> dict:
        """Search Gmail for executive emails."""
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 10)

        if not query:
            return {"success": False, "error": "No search query provided"}

        service, error = gmail_service()
        if error:
            return {"success": False, "error": error}

        def _search() -> list[dict]:
            messages = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
            email_list = []
            for msg in messages.get("messages", []):
                msg_data = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg["id"], format="metadata", metadataHeaders=["Subject", "From", "Date"])
                    .execute()
                )
                headers = header_map(msg_data.get("payload", {}))
                email_list.append(
                    {
                        "message_id": msg["id"],
                        "subject": headers.get("Subject", "(no subject)"),
                        "from": headers.get("From", ""),
                        "date": headers.get("Date", ""),
                        "snippet": msg_data.get("snippet", "")[:150],
                    }
                )
            return email_list

        try:
            email_list = await asyncio.to_thread(_search)
        except gmail_errors() as e:
            logger.error("Gmail search failed: %s", e)
            return {"success": False, "error": str(e)}
        return {"success": True, "emails": email_list, "count": len(email_list)}

    async def _handle_read_gmail_message(self, **kwargs) -> dict:
        """Read a Gmail message by ID and return the plain text body."""
        message_id = kwargs.get("message_id", "")
        if not message_id:
            return {"success": False, "error": "No message_id provided"}

        service, error = gmail_service()
        if error:
            return {"success": False, "error": error}

        def _read() -> dict:
            msg_data = service.users().messages().get(userId="me", id=message_id, format="full").execute()
            payload = msg_data.get("payload", {})
            headers = header_map(payload)
            return {
                "message_id": message_id,
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "date": headers.get("Date", ""),
                "body": flat_message_body(payload)[:_BODY_LIMIT],
            }

        try:
            result = await asyncio.to_thread(_read)
        except gmail_errors() as e:
            logger.error("Gmail read failed: %s", e)
            return {"success": False, "error": str(e)}
        return {"success": True, **result}

    async def _handle_backfill_executive_emails(self, **_kwargs) -> dict:
        """Backfill executive emails for the entire current quarter."""
        today = today_local()
        year, quarter = today.year, quarter_of(today)
        window = backfill_window(today, year, quarter)

        senders = get_executive_senders()
        if not senders:
            return {
                "success": False,
                "error": "No executive_senders configured in config.json",
            }

        service, error = gmail_service()
        if error:
            if error == _GMAIL_UNAVAILABLE:
                return {"success": False, "error": error}
            return {"success": False, "error": f"Gmail auth failed: {error}"}

        emails_dir = self.executive_emails_dir(year, quarter)
        emails_dir.mkdir(parents=True, exist_ok=True)

        backfill = await asyncio.to_thread(GmailBackfill, service, emails_dir, window)
        await asyncio.to_thread(backfill.run, senders)
        await asyncio.to_thread(self.update_summary, year, quarter)

        return {
            "success": True,
            "quarter": f"Q{quarter} {year}",
            "date_range": f"{window[0].isoformat()} to {window[1].isoformat()}",
            "total_new": backfill.totals["new"],
            "total_skipped": backfill.totals["skipped"],
            "senders": backfill.sender_results,
        }
