"""Parse executive emails and cache them for the stats daemon."""

import base64
import hashlib
import importlib
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

from server.paths import AA_CONFIG_DIR
from services.stats.handler_utils import now_local

logger = logging.getLogger(__name__)


ISSUE_KEY_RE = re.compile(r"((?:ANSTRAT|AAP|CAP)-\d+)")

# Section headers such as "Executive Summary" or "AI" on their own line.
SECTION_RE = re.compile(
    r"^(Executive Summary|AI|Customers?\s*[&]\s*Partners?|Risks?\s*/?\s*Issues?|"
    r"Associates?|Peer Requests?|Key Decisions?|Weekly Updates?|"
    r"Additional Info|Recurring|Life Events|Kudos|Arrivals|New Responsibilities)"
    r"\s*$",
    re.IGNORECASE | re.MULTILINE,
)

THEME_KEYWORDS: dict[str, list[str]] = {
    "AI / Machine Learning": [
        "ai",
        "machine learning",
        "llm",
        "lightspeed",
        "alia",
    ],
    "CI/CD & Pipelines": ["ci/cd", "pipeline", "konflux", "build", "release"],
    "Security & Compliance": [
        "security",
        "cra",
        "vulnerability",
        "dast",
        "compliance",
        "cve",
    ],
    "Customer Success": [
        "customer",
        "cisco",
        "telstra",
        "azure",
        "westpac",
        "wells fargo",
    ],
    "Python / Django Upgrades": ["python 3.12", "django", "upgrade"],
    "Operator & Infrastructure": [
        "operator",
        "infrastructure",
        "sre",
        "rosa",
        "redis",
    ],
    "Quality & Testing": ["test", "quality", "testathon", "qa"],
    "Documentation & Standards": ["openapi", "spec", "documentation", "standardiz"],
    "Team & People": [
        "onboard",
        "hiring",
        "intern",
        "kudos",
        "f2f",
        "face-to-face",
    ],
}


def _leading_sender(text: str) -> str:
    """Return the name before a leading "Name <address>", or "".

    Same result as re.match(r"(.+?)\\s*<([^>]+)>", text).group(1).strip(),
    computed in one pass: that lazy pattern backtracks polynomially when no
    address follows.
    """
    line_end = text.find("\n")
    if line_end < 0:
        line_end = len(text)
    j = 0
    close = -1
    for i in range(1, line_end + 1):
        j = max(j, i)
        while j < len(text) and text[j].isspace():
            j += 1
        if j < len(text) and text[j] == "<":
            if close < j + 1:
                close = text.find(">", j + 1)
                if close < 0:
                    return ""
            if close > j + 1:
                return text[:i].strip()
    return ""


def _extract_issue_keys(text: str) -> dict[str, list[str]]:
    """Return each issue key with the distinct contexts it appears in."""
    issue_keys_found: dict[str, list[str]] = {}
    for m in re.finditer(
        r"(?:^|\s)(.{0,80}?((?:ANSTRAT|AAP|CAP)-\d+).{0,80}?)(?:\s|$)",
        text,
        re.MULTILINE,
    ):
        contexts = issue_keys_found.setdefault(m.group(2), [])
        context = m.group(1).strip()[:120]
        if context not in contexts:
            contexts.append(context)
    return issue_keys_found


def _extract_priorities(text: str) -> list[dict]:
    """Return bracketed strategic priorities like [Build in 24], first seen wins."""
    priorities: list[dict] = []
    seen_priorities: set[str] = set()
    for m in re.finditer(
        r"\[([^\]]{3,60})\]\s*(.{0,200}?)(?=\[|\n\n|$)",
        text,
        re.DOTALL,
    ):
        name = m.group(1).strip()
        if name.lower() in seen_priorities:
            continue
        seen_priorities.add(name.lower())
        context = m.group(2).strip()[:200]
        priorities.append({"name": name, "context": context, "issue_keys": ISSUE_KEY_RE.findall(context)})
    return priorities


def _extract_sections(text: str, priorities: list[dict]) -> list[dict]:
    """Return known section headers with their body, keys and priorities."""
    section_starts = [(m.start(), m.group(1).strip()) for m in SECTION_RE.finditer(text)]
    sections: list[dict] = []
    for i, (start, header) in enumerate(section_starts):
        end = section_starts[i + 1][0] if i + 1 < len(section_starts) else len(text)
        body = text[start + len(header) : end].strip()[:500]
        priority_names = [
            p["name"] for p in priorities if p["name"] in body or any(k in body for k in p.get("issue_keys", []))
        ]
        sections.append(
            {
                "header": header,
                "body": body,
                "issue_keys": ISSUE_KEY_RE.findall(body),
                "priority_names": priority_names,
            }
        )
    return sections


def _extract_themes(text: str) -> list[dict]:
    """Return keyword themes found in the text, strongest first."""
    text_lower = text.lower()
    themes: list[dict] = []
    for theme_name, keywords in THEME_KEYWORDS.items():
        matches = [kw for kw in keywords if kw in text_lower]
        if matches:
            themes.append({"name": theme_name, "matched_keywords": matches, "strength": len(matches)})
    themes.sort(key=lambda t: -t["strength"])
    return themes


def parse_email_text(text: str) -> dict:
    """Parse executive email text into structured data.

    Extracts:
    - Section headers and their content
    - Strategic priorities (bracketed items like [Build in 24])
    - Issue keys (ANSTRAT-xxxx, AAP-xxxx, CAP-xxxx)
    - Themes via keyword matching
    """
    issue_keys_found = _extract_issue_keys(text)
    priorities = _extract_priorities(text)
    sections = _extract_sections(text, priorities)
    themes = _extract_themes(text)
    sender = _leading_sender(text)

    return {
        "priorities": priorities,
        "issue_keys": issue_keys_found,
        "sections": sections,
        "themes": themes,
        "sender": sender,
        "total_issue_keys": len(issue_keys_found),
        "total_priorities": len(priorities),
        "total_sections": len(sections),
        "total_themes": len(themes),
    }


def get_executive_senders() -> list[str]:
    """Load executive_senders from config.json."""
    config_paths = [
        Path(__file__).parent.parent.parent / "config.json",
        AA_CONFIG_DIR / "config.json",
    ]
    for cfg_path in config_paths:
        try:
            if cfg_path.exists():
                with open(cfg_path, encoding="utf-8") as f:
                    config = json.load(f)
                senders = config.get("performance", {}).get("executive_senders", [])
                if senders:
                    return senders
        except (OSError, ValueError, AttributeError):
            continue
    return []


def get_executive_emails_dir(perf_dir: Path) -> Path:
    """Get the directory for cached executive emails."""
    return perf_dir / "executive_emails"


def _gmail_errors() -> tuple[type[BaseException], ...]:
    """Errors a Gmail search or fetch can raise, including HttpError when installed."""
    errors: tuple[type[BaseException], ...] = (OSError, KeyError, ValueError, TypeError, AttributeError)
    try:
        return (*errors, importlib.import_module("googleapiclient.errors").HttpError)
    except ImportError:
        return errors


GMAIL_ERRORS = _gmail_errors()


def _load_existing_ids(emails_dir: Path) -> set[str]:
    """Return the Gmail message ids already cached in ``emails_dir``."""
    existing_ids: set[str] = set()
    for p in emails_dir.glob("*.json"):
        try:
            with open(p, encoding="utf-8") as fh:
                existing_ids.add(json.load(fh).get("gmail_message_id", ""))
        except (OSError, ValueError, AttributeError):
            continue
    return existing_ids


def _decode(data: str) -> str:
    """Decode base64url Gmail body data as UTF-8, replacing bad bytes."""
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")


def _part_body(parts: list[dict], mime_type: str) -> str:
    """Return the decoded body of the first ``mime_type`` part with data."""
    for part in parts:
        if part.get("mimeType") == mime_type:
            data = part.get("body", {}).get("data", "")
            if data:
                return _decode(data)
    return ""


def _message_body(payload: dict) -> str:
    """Return the plain-text body of a Gmail message payload.

    Prefers a text/plain part, then a text/html part with tags stripped,
    then the payload's own body.
    """
    parts = payload.get("parts", [])
    if parts:
        body = _part_body(parts, "text/plain")
        if body:
            return body
        raw_html = _part_body(parts, "text/html")
        if raw_html:
            body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw_html)).strip()
            if body:
                return body
    data = payload.get("body", {}).get("data", "")
    return _decode(data) if data else ""


def _cache_message(service, mid: str, sender: str, target: date, emails_dir: Path) -> str | None:
    """Fetch, parse and cache one Gmail message; return its email id or None."""
    msg_data = service.users().messages().get(userId="me", id=mid, format="full").execute()
    payload = msg_data.get("payload", {})
    header_map = {h["name"]: h["value"] for h in payload.get("headers", [])}

    body = _message_body(payload)
    if not body:
        return None

    parsed = parse_email_text(body[:10000])
    email_id = hashlib.sha256(f"{mid}:{sender}".encode()).hexdigest()[:12]
    parsed.update(
        {
            "email_id": email_id,
            "gmail_message_id": mid,
            "sender": header_map.get("From", sender),
            "sender_email": sender,
            "subject": header_map.get("Subject", ""),
            "email_date": header_map.get("Date", ""),
            "collected_date": target.isoformat(),
            "parsed_at": now_local().isoformat(),
            "text_preview": body[:300].replace("\n", " "),
        }
    )
    with open(emails_dir / f"{email_id}.json", "w", encoding="utf-8") as fh:
        json.dump(parsed, fh, indent=2)
    logger.info("Cached executive email from %s: %s", sender, parsed.get("subject", "")[:60])
    return email_id


def collect_executive_emails_for_date(target: date, perf_dir: Path) -> list[str]:
    """Fetch and parse executive emails for a given date.

    Searches Gmail for each configured sender, parses new emails,
    and caches them.  Returns list of newly cached email IDs.
    Runs synchronously (called from executor).
    """
    senders = get_executive_senders()
    if not senders:
        return []

    try:
        gmail = importlib.import_module("tool_modules.aa_gmail.src.tools_basic")
    except ImportError:
        logger.warning("Gmail module not available – skipping executive email collection")
        return []

    service, error = gmail.get_gmail_service()
    if error:
        logger.warning("Gmail auth failed – skipping executive emails: %s", error)
        return []

    emails_dir = get_executive_emails_dir(perf_dir)
    emails_dir.mkdir(parents=True, exist_ok=True)
    existing_ids = _load_existing_ids(emails_dir)
    query_dates = f"after:{target.isoformat()} before:{(target + timedelta(days=1)).isoformat()}"
    new_ids: list[str] = []

    for sender in senders:
        try:
            results = (
                service.users().messages().list(userId="me", q=f"from:{sender} {query_dates}", maxResults=20).execute()
            )
            for msg in results.get("messages", []):
                if msg["id"] in existing_ids:
                    continue
                email_id = _cache_message(service, msg["id"], sender, target, emails_dir)
                if email_id:
                    new_ids.append(email_id)
                    existing_ids.add(msg["id"])
        except GMAIL_ERRORS as e:
            logger.warning("Gmail search for %s on %s failed: %s", sender, target, e)

    return new_ids
