import base64
import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from server.paths import AA_CONFIG_DIR

logger = logging.getLogger(__name__)


def parse_email_text(text: str) -> dict:
    """Parse executive email text into structured data.

    Extracts:
    - Section headers and their content
    - Strategic priorities (bracketed items like [Build in 24])
    - Issue keys (ANSTRAT-xxxx, AAP-xxxx, CAP-xxxx)
    - Themes via keyword matching
    """
    # Extract issue keys with context
    issue_keys_found: dict[str, list[str]] = {}
    for m in re.finditer(
        r"(?:^|\s)(.{0,80}?((?:ANSTRAT|AAP|CAP)-\d+).{0,80}?)(?:\s|$)",
        text,
        re.MULTILINE,
    ):
        key = m.group(2)
        context = m.group(1).strip()[:120]
        if key not in issue_keys_found:
            issue_keys_found[key] = []
        if context not in issue_keys_found[key]:
            issue_keys_found[key].append(context)

    # Extract bracketed strategic priorities like [Build in 24], [Python 3.12]
    priorities: list[dict] = []
    seen_priorities: set[str] = set()
    for m in re.finditer(
        r"\[([^\]]{3,60})\]\s*(.{0,200}?)(?=\[|\n\n|$)",
        text,
        re.DOTALL,
    ):
        name = m.group(1).strip()
        context = m.group(2).strip()[:200]
        name_lower = name.lower()
        if name_lower not in seen_priorities:
            seen_priorities.add(name_lower)
            # Find issue keys within this priority's context
            prio_keys = re.findall(r"((?:ANSTRAT|AAP|CAP)-\d+)", context)
            priorities.append(
                {
                    "name": name,
                    "context": context,
                    "issue_keys": prio_keys,
                }
            )

    # Extract section headers (lines that look like "Executive Summary", "AI", etc.)
    sections: list[dict] = []
    section_pattern = re.compile(
        r"^(Executive Summary|AI|Customers?\s*[&]\s*Partners?|Risks?\s*/?\s*Issues?|"
        r"Associates?|Peer Requests?|Key Decisions?|Weekly Updates?|"
        r"Additional Info|Recurring|Life Events|Kudos|Arrivals|New Responsibilities)"
        r"\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    section_starts = [
        (m.start(), m.group(1).strip()) for m in section_pattern.finditer(text)
    ]

    for i, (start, header) in enumerate(section_starts):
        end = section_starts[i + 1][0] if i + 1 < len(section_starts) else len(text)
        body = text[start + len(header) : end].strip()[:500]
        section_keys = re.findall(r"((?:ANSTRAT|AAP|CAP)-\d+)", body)
        section_priorities = [
            p
            for p in priorities
            if any(pk in body for pk in [p["name"]])
            or any(k in body for k in p.get("issue_keys", []))
        ]
        sections.append(
            {
                "header": header,
                "body": body,
                "issue_keys": section_keys,
                "priority_names": [p["name"] for p in section_priorities],
            }
        )

    # Extract themes via keyword matching
    text_lower = text.lower()
    theme_keywords = {
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
    themes: list[dict] = []
    for theme_name, keywords in theme_keywords.items():
        matches = [kw for kw in keywords if kw in text_lower]
        if matches:
            themes.append(
                {
                    "name": theme_name,
                    "matched_keywords": matches,
                    "strength": len(matches),
                }
            )
    themes.sort(key=lambda t: -t["strength"])

    # Try to extract sender and date from text
    sender = ""
    email_date = ""
    sender_match = re.search(r"^(.+?)\s*<([^>]+)>", text)
    if sender_match:
        sender = sender_match.group(1).strip()

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
        except Exception:
            continue
    return []


def get_executive_emails_dir(perf_dir: Path) -> Path:
    """Get the directory for cached executive emails."""
    return perf_dir / "executive_emails"


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
        from tool_modules.aa_gmail.src.tools_basic import get_gmail_service
    except ImportError:
        logger.warning(
            "Gmail module not available – skipping executive email collection"
        )
        return []

    service, error = get_gmail_service()
    if error:
        logger.warning(f"Gmail auth failed – skipping executive emails: {error}")
        return []

    emails_dir = get_executive_emails_dir(perf_dir)
    emails_dir.mkdir(parents=True, exist_ok=True)

    existing_ids: set[str] = set()
    for p in emails_dir.glob("*.json"):
        try:
            with open(p, encoding="utf-8") as fh:
                existing_ids.add(json.load(fh).get("gmail_message_id", ""))
        except Exception:
            pass

    after_str = target.isoformat()
    before_date = target + timedelta(days=1)
    before_str = before_date.isoformat()
    new_ids: list[str] = []

    for sender in senders:
        query = f"from:{sender} after:{after_str} before:{before_str}"
        try:
            results = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=20)
                .execute()
            )
            messages = results.get("messages", [])
            for msg in messages:
                mid = msg["id"]
                if mid in existing_ids:
                    continue

                msg_data = (
                    service.users()
                    .messages()
                    .get(userId="me", id=mid, format="full")
                    .execute()
                )
                payload = msg_data.get("payload", {})
                headers = payload.get("headers", [])
                header_map = {h["name"]: h["value"] for h in headers}

                body = ""
                parts = payload.get("parts", [])
                if parts:
                    for part in parts:
                        if part.get("mimeType") == "text/plain":
                            data = part.get("body", {}).get("data", "")
                            if data:
                                body = base64.urlsafe_b64decode(data).decode(
                                    "utf-8", errors="replace"
                                )
                                break
                    if not body:
                        for part in parts:
                            if part.get("mimeType") == "text/html":
                                data = part.get("body", {}).get("data", "")
                                if data:
                                    raw_html = base64.urlsafe_b64decode(data).decode(
                                        "utf-8", errors="replace"
                                    )
                                    body = re.sub(r"<[^>]+>", " ", raw_html)
                                    body = re.sub(r"\s+", " ", body).strip()
                                    break
                if not body:
                    data = payload.get("body", {}).get("data", "")
                    if data:
                        body = base64.urlsafe_b64decode(data).decode(
                            "utf-8", errors="replace"
                        )

                if not body:
                    continue

                parsed = parse_email_text(body[:10000])

                email_id = hashlib.sha256(f"{mid}:{sender}".encode()).hexdigest()[:12]

                parsed["email_id"] = email_id
                parsed["gmail_message_id"] = mid
                parsed["sender"] = header_map.get("From", sender)
                parsed["sender_email"] = sender
                parsed["subject"] = header_map.get("Subject", "")
                parsed["email_date"] = header_map.get("Date", "")
                parsed["collected_date"] = target.isoformat()
                parsed["parsed_at"] = datetime.now().isoformat()
                parsed["text_preview"] = body[:300].replace("\n", " ")

                cache_file = emails_dir / f"{email_id}.json"
                with open(cache_file, "w", encoding="utf-8") as fh:
                    json.dump(parsed, fh, indent=2)

                new_ids.append(email_id)
                existing_ids.add(mid)
                logger.info(
                    f"Cached executive email from {sender}: {parsed.get('subject', '')[:60]}"
                )

        except Exception as e:
            logger.warning(f"Gmail search for {sender} on {target} failed: {e}")

    return new_ids
