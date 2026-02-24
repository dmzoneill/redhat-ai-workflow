"""ANSTRAT Issue Catalog & Passive Ownership Discovery.

Builds a catalog of all ANSTRAT Initiative, Feature, and Outcome issues, then
discovers strategic ownership passively through signals like:
  - Jira reporter (who filed it = who cares about it strategically)
  - Emails mentioning the issue or related themes
  - Google Drive documents on related topics
  - Jira comments / activity

Ownership is NEVER derived from the Jira assignee field, because assignees
are typically the engineers doing the work, not the executives who own the
strategic direction.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from server.utils import run_cmd_sync

logger = logging.getLogger(__name__)

ANSTRAT_ISSUE_TYPES = ("Initiative", "Feature", "Outcome")

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

# Target executives whose strategic ownership we want to discover passively.
# The usernames list is used for JQL reporter/creator queries.
SENDER_JIRA_USERNAMES = {
    "sharwell@redhat.com": ["sharwell", "rh-ee-sharwell"],
    "jhardy@redhat.com": ["jhardy", "rh-ee-jhardy"],
    "dmendoza@redhat.com": ["dmendoza", "rh-ee-dmendoza"],
}

DISPLAY_NAME_TO_EMAIL: dict[str, str] = {
    "scott harwell": "sharwell@redhat.com",
    "john hardy": "jhardy@redhat.com",
    "dafne mendoza": "dmendoza@redhat.com",
}


def _extract_themes(summary: str, max_themes: int = 5) -> list[str]:
    """Extract meaningful theme keywords from an issue summary."""
    words = re.findall(r"[A-Za-z]{3,}", summary)
    themes = []
    for w in words:
        lower = w.lower()
        if lower not in STOP_WORDS and lower not in themes:
            themes.append(lower)
        if len(themes) >= max_themes:
            break
    return themes


# ---------------------------------------------------------------------------
# ANSTRAT Issue Catalog (no ownership assignment)
# ---------------------------------------------------------------------------


def sync_anstrat_catalog(perf_dir: Path) -> dict:
    """Fetch ANSTRAT issues and build a flat catalog (no ownership).

    Returns a dict of issues keyed by ANSTRAT key, each with summary,
    type, status, and extracted themes.  The catalog is consumed by the
    relationship builder which discovers ownership from passive signals.
    """
    type_filter = ", ".join(f'"{t}"' for t in ANSTRAT_ISSUE_TYPES)
    jql = (
        f"project = ANSTRAT AND issuetype in ({type_filter}) " f"ORDER BY updated DESC"
    )

    issues: dict[str, dict] = {}

    try:
        success, output = run_cmd_sync(
            ["rh-issue", "search", jql, "--max-results", "200"],
            timeout=90,
        )
        if not success:
            logger.warning(f"ANSTRAT catalog sync failed: {output[:200]}")
            return _load_cached_catalog(perf_dir)

        for line in output.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 5:
                continue
            key = parts[0]
            if not key.startswith("ANSTRAT-"):
                continue

            summary = parts[4] if len(parts) > 4 else ""
            issues[key] = {
                "summary": summary,
                "type": (parts[1] if len(parts) > 1 else "").strip(),
                "status": (parts[2] if len(parts) > 2 else "").strip(),
                "themes": _extract_themes(summary, max_themes=8),
            }

    except Exception as e:
        logger.warning(f"ANSTRAT catalog sync failed: {e}")
        return _load_cached_catalog(perf_dir)

    catalog = {
        "issues": issues,
        "last_synced": datetime.now().isoformat(),
    }

    perf_dir.mkdir(parents=True, exist_ok=True)
    out_file = perf_dir / "anstrat_catalog.json"
    try:
        with open(out_file, "w", encoding="utf-8") as fh:
            json.dump(catalog, fh, indent=2)
        logger.info(f"ANSTRAT catalog synced: {len(issues)} issues")
    except Exception as e:
        logger.warning(f"Failed to write catalog file: {e}")

    return catalog


def load_anstrat_catalog(perf_dir: Path) -> dict:
    """Load the cached ANSTRAT issue catalog."""
    return _load_cached_catalog(perf_dir)


def _load_cached_catalog(perf_dir: Path) -> dict:
    out_file = perf_dir / "anstrat_catalog.json"
    if out_file.exists():
        try:
            with open(out_file, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as e:
            logger.warning("Loading cached ANSTRAT catalog: %s", e)
            pass
    return {"issues": {}, "last_synced": None}


# Legacy compat: callers that use load_anstrat_ownership get the catalog
# wrapped in the old shape (empty owners, issues only).
def sync_anstrat_ownership(perf_dir: Path) -> dict:
    """Legacy wrapper -- syncs catalog and returns old-shape dict."""
    catalog = sync_anstrat_catalog(perf_dir)
    return {
        "owners": {},
        "issues": catalog.get("issues", {}),
        "last_synced": catalog.get("last_synced"),
    }


def load_anstrat_ownership(perf_dir: Path) -> dict:
    """Legacy wrapper -- loads catalog in old-shape dict."""
    catalog = load_anstrat_catalog(perf_dir)
    return {
        "owners": {},
        "issues": catalog.get("issues", {}),
        "last_synced": catalog.get("last_synced"),
    }


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _normalize_person(raw: str) -> str:
    """Convert a Jira person string to a normalised email address."""
    raw = raw.strip()
    if "@" in raw:
        return raw.lower()
    lookup = DISPLAY_NAME_TO_EMAIL.get(raw.lower())
    if lookup:
        return lookup
    clean = raw.replace("rh-ee-", "").replace("rh-", "")
    if clean:
        return f"{clean}@redhat.com"
    return ""


def _display_name(raw: str) -> str:
    """Best-effort display name from a Jira person field."""
    raw = raw.strip()
    if "@" in raw:
        return raw.split("@")[0].replace(".", " ").replace("-", " ").title()
    clean = raw.replace("rh-ee-", "").replace("rh-", "")
    return clean.replace(".", " ").replace("-", " ").title()


def _build_person_clause(email: str, field: str = "reporter") -> str:
    """Build a Jira JQL IN clause for reporter/creator (NOT assignee)."""
    usernames = SENDER_JIRA_USERNAMES.get(email, [])
    candidates = [f'"{email}"'] + [f'"{u}"' for u in usernames]
    return f"{field} in ({', '.join(candidates)})"


# ---------------------------------------------------------------------------
# Passive Jira Signals (reporter, creator -- NOT assignee)
# ---------------------------------------------------------------------------


def sync_sender_jira_activity(
    perf_dir: Path,
    sender_emails: list[str] | None = None,
    days: int = 90,
) -> dict:
    """Discover ANSTRAT issues that target senders care about via passive signals.

    Queries for issues where each sender is the **reporter** or **creator**
    (i.e. they filed it, so they care about it strategically).  Does NOT use
    the assignee field, because assignees are the engineers doing the work.
    """
    if sender_emails is None:
        sender_emails = list(SENDER_JIRA_USERNAMES.keys())

    activity: dict[str, dict] = {}

    for email in sender_emails:
        reporter_clause = _build_person_clause(email, "reporter")
        jql = (
            f"{reporter_clause} AND project in (ANSTRAT, AAP, AAPRFE) "
            f"AND updated >= -{days}d ORDER BY updated DESC"
        )

        issues: list[dict] = []
        themes: list[str] = []
        try:
            success, output = run_cmd_sync(
                ["rh-issue", "search", jql, "--max-results", "50"],
                timeout=90,
            )
            if success:
                for line in output.splitlines():
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) < 5:
                        continue
                    key = parts[0]
                    if not re.match(r"^[A-Z]+-\d+$", key):
                        continue
                    summary = parts[4] if len(parts) > 4 else ""
                    issue_type = parts[1] if len(parts) > 1 else ""
                    status = parts[2] if len(parts) > 2 else ""
                    issues.append(
                        {
                            "key": key,
                            "summary": summary,
                            "type": issue_type.strip(),
                            "status": status.strip(),
                            "signal": "reporter",
                        }
                    )
                    for t in _extract_themes(summary):
                        if t not in themes:
                            themes.append(t)
            else:
                logger.warning(f"Jira reporter query for {email}: {output[:200]}")
        except Exception as e:
            logger.warning(f"Jira activity sync for {email} failed: {e}")

        activity[email] = {
            "display_name": _display_name(email.split("@")[0]),
            "issues": issues,
            "themes": themes[:20],
            "issue_count": len(issues),
            "projects": list({i["key"].split("-")[0] for i in issues}),
            "signal_types": ["reporter"],
            "last_synced": datetime.now().isoformat(),
        }

    result_data = {
        "sender_activity": activity,
        "last_synced": datetime.now().isoformat(),
        "days_lookback": days,
    }

    perf_dir.mkdir(parents=True, exist_ok=True)
    out_file = perf_dir / "sender_jira_activity.json"
    try:
        with open(out_file, "w", encoding="utf-8") as fh:
            json.dump(result_data, fh, indent=2)
        total = sum(a["issue_count"] for a in activity.values())
        logger.info(
            f"Sender Jira activity synced (reporter): "
            f"{len(activity)} senders, {total} issues"
        )
    except Exception as e:
        logger.warning(f"Failed to write sender activity file: {e}")

    return result_data


def load_sender_jira_activity(perf_dir: Path) -> dict:
    """Load cached sender Jira activity from disk."""
    out_file = perf_dir / "sender_jira_activity.json"
    if out_file.exists():
        try:
            with open(out_file, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as e:
            logger.warning("Loading cached sender Jira activity: %s", e)
            pass
    return {"sender_activity": {}, "last_synced": None}


# ---------------------------------------------------------------------------
# Google Drive Document Discovery
# ---------------------------------------------------------------------------


def sync_sender_gdrive_docs(
    perf_dir: Path,
    sender_emails: list[str] | None = None,
    search_terms: list[str] | None = None,
) -> dict:
    """Search Google Drive for strategy-related documents.

    Uses the Google Drive API to find docs related to each sender's domain.
    Documents where a sender is owner or last modifier count as a strong
    passive signal; keyword-matched docs count as a weaker signal.
    """
    if sender_emails is None:
        sender_emails = list(SENDER_JIRA_USERNAMES.keys())

    if search_terms is None:
        search_terms = [
            "ANSTRAT",
            "Ansible strategy",
            "Workflow Automation",
            "Event Driven Ansible",
            "platform roadmap",
        ]

    try:
        from tool_modules.aa_gdrive.src.tools_basic import get_drive_service
    except ImportError:
        logger.warning("Google Drive module not available")
        return {"documents": [], "last_synced": None}

    service, error = get_drive_service()
    if error:
        logger.warning(f"Google Drive not authenticated: {error}")
        return {"documents": [], "last_synced": None}

    sender_names = {
        email: _display_name(email.split("@")[0]) for email in sender_emails
    }

    queries = list(search_terms)
    for name in sender_names.values():
        queries.append(name)

    seen_ids: set[str] = set()
    documents: list[dict] = []

    for query in queries:
        escaped = query.replace("\\", "\\\\").replace("'", "\\'")
        search_query = (
            f"fullText contains '{escaped}' and trashed = false "
            f"and modifiedTime > '{_ninety_days_ago()}'"
        )
        try:
            results = (
                service.files()
                .list(
                    q=search_query,
                    pageSize=10,
                    fields="files(id, name, mimeType, modifiedTime, webViewLink, owners, lastModifyingUser)",
                    orderBy="modifiedTime desc",
                )
                .execute()
            )
            for f in results.get("files", []):
                fid = f.get("id", "")
                if fid in seen_ids:
                    continue
                seen_ids.add(fid)

                owner_emails = [
                    o.get("emailAddress", "").lower() for o in f.get("owners", [])
                ]
                last_modifier = (
                    f.get("lastModifyingUser", {}).get("emailAddress", "").lower()
                )

                related_senders = [
                    email
                    for email in sender_emails
                    if email in owner_emails or email == last_modifier
                ]
                relevance = "direct" if related_senders else "keyword"

                doc_entry = {
                    "id": fid,
                    "name": f.get("name", ""),
                    "mime_type": f.get("mimeType", ""),
                    "modified": f.get("modifiedTime", ""),
                    "url": f.get("webViewLink", ""),
                    "owners": owner_emails,
                    "last_modifier": last_modifier,
                    "related_senders": related_senders,
                    "relevance": relevance,
                    "matched_query": query,
                }
                documents.append(doc_entry)
        except Exception as e:
            logger.debug(f"Drive search for '{query}' failed: {e}")

    documents.sort(
        key=lambda d: (d["relevance"] != "direct", d.get("modified", "")),
        reverse=False,
    )
    documents = documents[:50]

    result_data = {
        "documents": documents,
        "sender_names": sender_names,
        "last_synced": datetime.now().isoformat(),
    }

    perf_dir.mkdir(parents=True, exist_ok=True)
    out_file = perf_dir / "sender_gdrive_docs.json"
    try:
        with open(out_file, "w", encoding="utf-8") as fh:
            json.dump(result_data, fh, indent=2)
        logger.info(f"Sender GDrive docs synced: {len(documents)} documents")
    except Exception as e:
        logger.warning(f"Failed to write GDrive docs file: {e}")

    return result_data


def load_sender_gdrive_docs(perf_dir: Path) -> dict:
    """Load cached sender Google Drive documents from disk."""
    out_file = perf_dir / "sender_gdrive_docs.json"
    if out_file.exists():
        try:
            with open(out_file, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as e:
            logger.warning("Loading cached sender GDrive docs: %s", e)
            pass
    return {"documents": [], "last_synced": None}


def _ninety_days_ago() -> str:
    """Return ISO date string for 90 days ago."""
    from datetime import timedelta

    return (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00")
