"""Google Drive contribution collector for QC data capture.

Discovers and classifies user contributions from Google Docs, Slides, and Sheets
for the quarterly contribution scoring system. Integrates with the existing
event pipeline in collector.py.

Supports two modes:
  - Personal: Files the authenticated user owns/edited (existing OAuth user context)
  - Shared Drive: Files from a Team Drive with per-user attribution via revision
    and comment history. This enables peer data capture by querying the shared
    drive once, caching the result, and filtering events per peer email.

Data flow:
  1. File Discovery: Drive API files.list filtered by quarter + MIME type
  2. Revision Analysis: revisions.list per file for contribution depth
  3. Comment Analysis: comments.list per file for review/collaboration depth
  4. Filename Classification: pattern matching -> contribution type
  5. Event Emission: structured events compatible with collector.py pipeline
  6. Caching: quarterly cache to avoid redundant API calls

Comment interactions captured:
  - Comments authored, replies authored, threads resolved
  - @mentions received, comment assignments
  - Comment-only events for review-without-edit contributions
"""

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path

from services.stats.quarter_utils import QUARTER_STARTS

logger = logging.getLogger(__name__)

GOOGLE_MIME_TYPES = {
    "application/vnd.google-apps.document": "doc",
    "application/vnd.google-apps.spreadsheet": "sheet",
    "application/vnd.google-apps.presentation": "slides",
}

MIME_TYPE_LABELS = {
    "doc": "Google Doc",
    "sheet": "Google Sheet",
    "slides": "Google Slides",
}

# ---------------------------------------------------------------------------
# Filename Classification Rules
# ---------------------------------------------------------------------------
# Each rule: (pattern_list, classification_name, primary_competencies)
# Patterns are matched case-insensitively against the filename.

FILENAME_CLASSIFICATION_RULES: list[tuple[list[str], str, list[str]]] = [
    # Presentations / Speaking
    (
        [
            "presentation",
            "slides",
            "deck",
            "talk",
            "lightning",
            "keynote",
            "demo day",
            "show and tell",
            "all-hands",
            "tech talk",
        ],
        "presentation",
        ["speaking_publicity"],
    ),
    # Architecture / Design documents
    (
        [
            "architecture",
            "design doc",
            "adr",
            "rfc",
            "technical design",
            "system design",
            "design proposal",
            "design review",
        ],
        "architecture_doc",
        ["technical_knowledge", "creativity_innovation"],
    ),
    # Runbooks / Operational docs
    (
        [
            "runbook",
            "playbook",
            "sop",
            "standard operating",
            "troubleshoot",
            "incident response",
            "on-call",
            "oncall",
            "operations guide",
        ],
        "operational_doc",
        ["continuous_improvement", "technical_knowledge"],
    ),
    # Planning / Strategy docs
    (
        [
            "sprint planning",
            "sprint plan",
            "roadmap",
            "okr",
            "objective",
            "quarterly plan",
            "strategy",
            "anstrat",
            "initiative",
        ],
        "planning_doc",
        ["planning_execution", "leadership"],
    ),
    # Process / Retro docs
    (
        [
            "retrospective",
            "retro",
            "postmortem",
            "post-mortem",
            "lessons learned",
            "process improvement",
            "blameless",
        ],
        "process_doc",
        ["continuous_improvement"],
    ),
    # Mentorship / Training docs
    (
        [
            "onboarding",
            "mentor",
            "training",
            "newcomer",
            "ramp-up",
            "brown bag",
            "lunch and learn",
            "knowledge share",
            "workshop",
        ],
        "mentorship_doc",
        ["mentorship"],
    ),
    # Status / Reporting docs
    (
        [
            "standup",
            "status update",
            "status report",
            "weekly update",
            "weekly report",
            "progress report",
            "meeting notes",
            "minutes",
        ],
        "status_doc",
        ["evidence_record"],
    ),
    # Budget / Tracking sheets
    (
        [
            "budget",
            "forecast",
            "tracker",
            "tracking",
            "capacity",
            "resource plan",
            "headcount",
            "staffing",
        ],
        "planning_sheet",
        ["planning_execution"],
    ),
    # Customer-facing docs
    (
        [
            "customer",
            "feedback",
            "support",
            "escalation",
            "account review",
            "customer success",
            "field",
            "use case",
            "case study",
        ],
        "customer_doc",
        ["customer_focus"],
    ),
    # Research / Innovation docs
    (
        [
            "research",
            "poc",
            "proof of concept",
            "prototype",
            "experiment",
            "spike",
            "investigation",
            "feasibility",
            "benchmark",
        ],
        "research_doc",
        ["creativity_innovation"],
    ),
]

# Default competency mapping by MIME type when no filename pattern matches
MIME_TYPE_DEFAULT_COMPETENCIES = {
    "slides": ["speaking_publicity"],
    "sheet": ["planning_execution", "evidence_record"],
    "doc": ["technical_knowledge", "evidence_record"],
}


def classify_filename(name: str, mime_short: str) -> tuple[str, list[str]]:
    """Classify a Google Drive file by its name and MIME type.

    Returns (classification_name, list_of_competency_ids).
    """
    lower = name.lower()
    for patterns, classification, competencies in FILENAME_CLASSIFICATION_RULES:
        for pattern in patterns:
            if pattern in lower:
                return classification, competencies

    return f"general_{mime_short}", MIME_TYPE_DEFAULT_COMPETENCIES.get(mime_short, [])


# ---------------------------------------------------------------------------
# Rate-Limited Drive API Helpers
# ---------------------------------------------------------------------------

_MIN_REQUEST_INTERVAL = 0.1  # 100ms between requests
_last_request_time = 0.0


def _rate_limit():
    """Enforce minimum interval between Drive API requests."""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def _api_call_with_backoff(fn, max_retries: int = 3):
    """Execute a Drive API call with exponential backoff on rate limit errors."""
    for attempt in range(max_retries):
        _rate_limit()
        try:
            return fn()
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rateLimitExceeded" in error_str:
                wait = (2**attempt) * 1.0
                logger.warning(
                    "Drive API rate limited, retrying in %.1fs (attempt %d/%d)",
                    wait,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(wait)
                continue
            raise
    return fn()


# ---------------------------------------------------------------------------
# File Discovery
# ---------------------------------------------------------------------------


def discover_files(
    service,
    user_email: str,
    quarter_start: str,
    quarter_end: str | None = None,
) -> list[dict]:
    """Discover Google Docs/Sheets/Slides modified in the quarter.

    Returns list of file metadata dicts with classification info.
    """
    mime_filter = " or ".join(f"mimeType='{m}'" for m in GOOGLE_MIME_TYPES)
    q = (
        f"({mime_filter})"
        f" and modifiedTime >= '{quarter_start}'"
        f" and trashed = false"
    )
    if quarter_end:
        q += f" and modifiedTime < '{quarter_end}'"

    fields = (
        "nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, "
        "modifiedByMeTime, owners, lastModifyingUser, webViewLink, description)"
    )

    all_files: list[dict] = []
    page_token = None

    while True:
        resp = _api_call_with_backoff(
            lambda pt=page_token: service.files()
            .list(
                q=q,
                fields=fields,
                pageSize=200,
                orderBy="modifiedTime desc",
                pageToken=pt,
            )
            .execute()
        )
        raw_files = resp.get("files", [])

        for f in raw_files:
            mime = f.get("mimeType", "")
            mime_short = GOOGLE_MIME_TYPES.get(mime, "unknown")

            owner_emails = [
                o.get("emailAddress", "").lower() for o in f.get("owners", [])
            ]
            last_modifier = (
                f.get("lastModifyingUser", {}).get("emailAddress", "").lower()
            )

            is_owner = user_email.lower() in owner_emails
            is_modifier = user_email.lower() == last_modifier
            modified_by_me = f.get("modifiedByMeTime")
            has_my_edits = modified_by_me is not None

            if has_my_edits and modified_by_me:
                try:
                    mbm_date = datetime.fromisoformat(
                        modified_by_me.replace("Z", "+00:00")
                    ).date()
                    qs_date = datetime.fromisoformat(
                        quarter_start.replace("Z", "+00:00")
                    ).date()
                    has_my_edits_in_quarter = mbm_date >= qs_date
                except (ValueError, TypeError):
                    has_my_edits_in_quarter = has_my_edits
            else:
                has_my_edits_in_quarter = False

            classification, competencies = classify_filename(f["name"], mime_short)

            role = "viewer"
            if is_owner:
                role = "owner"
            elif is_modifier:
                role = "contributor"
            elif has_my_edits_in_quarter:
                role = "contributor"

            if role == "viewer" and not has_my_edits_in_quarter:
                continue

            created_time = f.get("createdTime", "")
            created_in_quarter = False
            if created_time:
                try:
                    ct = datetime.fromisoformat(
                        created_time.replace("Z", "+00:00")
                    ).date()
                    qs = datetime.fromisoformat(
                        quarter_start.replace("Z", "+00:00")
                    ).date()
                    created_in_quarter = ct >= qs and is_owner
                except (ValueError, TypeError):
                    pass

            all_files.append(
                {
                    "id": f["id"],
                    "name": f["name"],
                    "mime_type": mime,
                    "mime_short": mime_short,
                    "created_time": created_time,
                    "modified_time": f.get("modifiedTime", ""),
                    "modified_by_me_time": modified_by_me or "",
                    "url": f.get("webViewLink", ""),
                    "owners": owner_emails,
                    "last_modifier": last_modifier,
                    "role": role,
                    "is_owner": is_owner,
                    "created_in_quarter": created_in_quarter,
                    "has_my_edits_in_quarter": has_my_edits_in_quarter,
                    "classification": classification,
                    "competencies": competencies,
                    "description": f.get("description", ""),
                }
            )

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    logger.info(
        "GDrive: discovered %d files (%d with user contributions) for quarter starting %s",
        len(raw_files),
        len(all_files),
        quarter_start[:10],
    )
    return all_files


# ---------------------------------------------------------------------------
# Revision Analysis
# ---------------------------------------------------------------------------


def get_revision_stats(
    service,
    file_id: str,
    user_email: str,
    quarter_start: str,
) -> dict:
    """Analyze revision history for a file to measure contribution depth.

    Returns stats about the user's revisions in the quarter.
    """
    try:
        resp = _api_call_with_backoff(
            lambda: service.revisions()
            .list(
                fileId=file_id,
                fields="revisions(id, modifiedTime, lastModifyingUser)",
                pageSize=200,
            )
            .execute()
        )
    except Exception as e:
        logger.debug("Failed to get revisions for %s: %s", file_id, e)
        return {
            "total_revisions": 0,
            "user_revisions_in_quarter": 0,
            "first_user_revision": None,
            "last_user_revision": None,
        }

    revisions = resp.get("revisions", [])
    user_lower = user_email.lower()

    try:
        qs_dt = datetime.fromisoformat(quarter_start.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        qs_dt = datetime(2026, 1, 1)

    user_revisions_in_quarter = 0
    first_rev = None
    last_rev = None

    for rev in revisions:
        rev_user = rev.get("lastModifyingUser", {}).get("emailAddress", "").lower()
        rev_time_str = rev.get("modifiedTime", "")

        if rev_user != user_lower:
            continue

        try:
            rev_time = datetime.fromisoformat(rev_time_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        if rev_time >= qs_dt:
            user_revisions_in_quarter += 1
            if first_rev is None or rev_time_str < first_rev:
                first_rev = rev_time_str
            if last_rev is None or rev_time_str > last_rev:
                last_rev = rev_time_str

    return {
        "total_revisions": len(revisions),
        "user_revisions_in_quarter": user_revisions_in_quarter,
        "first_user_revision": first_rev,
        "last_user_revision": last_rev,
    }


# ---------------------------------------------------------------------------
# Comment Analysis
# ---------------------------------------------------------------------------

_COMMENT_FIELDS = (
    "comments(id, content, author, createdTime, modifiedTime, resolved, "
    "replies(author, content, createdTime, action), "
    "mentionedEmailAddresses, assigneeEmailAddress)"
)


def get_comment_stats(
    service,
    file_id: str,
    user_email: str,
    quarter_start: str,
) -> dict:
    """Analyze comment activity for a file to measure review/collaboration depth.

    Fetches all comments modified since quarter_start and tallies per-user
    interaction: authored comments, authored replies, resolved threads,
    mentions, and assignments.

    Returns a dict with counts and total_comments on the file.
    """
    user_lower = user_email.lower()

    stats = {
        "total_comments": 0,
        "comments_authored": 0,
        "replies_authored": 0,
        "comments_resolved": 0,
        "comments_mentioned_in": 0,
        "comments_assigned_to": 0,
    }

    page_token = None
    while True:
        try:
            resp = _api_call_with_backoff(
                lambda pt=page_token: service.comments()
                .list(
                    fileId=file_id,
                    fields=f"nextPageToken, {_COMMENT_FIELDS}",
                    pageSize=100,
                    startModifiedTime=quarter_start,
                    pageToken=pt,
                )
                .execute()
            )
        except Exception as e:
            logger.debug("Failed to get comments for %s: %s", file_id, e)
            return stats

        comments = resp.get("comments", [])
        stats["total_comments"] += len(comments)

        for comment in comments:
            author_email = comment.get("author", {}).get("emailAddress", "").lower()
            if author_email == user_lower:
                stats["comments_authored"] += 1

            mentioned = [e.lower() for e in comment.get("mentionedEmailAddresses", [])]
            if user_lower in mentioned:
                stats["comments_mentioned_in"] += 1

            assignee = (comment.get("assigneeEmailAddress") or "").lower()
            if assignee == user_lower:
                stats["comments_assigned_to"] += 1

            for reply in comment.get("replies", []):
                reply_author = reply.get("author", {}).get("emailAddress", "").lower()
                if reply_author == user_lower:
                    stats["replies_authored"] += 1
                    if reply.get("action") == "resolve":
                        stats["comments_resolved"] += 1

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return stats


def get_file_comment_stats_for_all_users(
    service,
    file_id: str,
    quarter_start: str,
) -> dict[str, dict]:
    """Analyze comment activity for all users on a shared drive file.

    Returns {email: {comments_authored, replies_authored, ...}} for every
    user who interacted via comments. Used for shared drive peer indexing.
    """
    per_user: dict[str, dict] = {}
    page_token = None

    def _ensure_user(email: str) -> dict:
        if email not in per_user:
            per_user[email] = {
                "comments_authored": 0,
                "replies_authored": 0,
                "comments_resolved": 0,
                "comments_mentioned_in": 0,
                "comments_assigned_to": 0,
            }
        return per_user[email]

    while True:
        try:
            resp = _api_call_with_backoff(
                lambda pt=page_token: service.comments()
                .list(
                    fileId=file_id,
                    fields=f"nextPageToken, {_COMMENT_FIELDS}",
                    pageSize=100,
                    startModifiedTime=quarter_start,
                    pageToken=pt,
                )
                .execute()
            )
        except Exception as e:
            logger.debug("Failed to get comments for shared file %s: %s", file_id, e)
            return per_user

        for comment in resp.get("comments", []):
            author_email = comment.get("author", {}).get("emailAddress", "").lower()
            if author_email:
                _ensure_user(author_email)["comments_authored"] += 1

            for email in comment.get("mentionedEmailAddresses", []):
                _ensure_user(email.lower())["comments_mentioned_in"] += 1

            assignee = (comment.get("assigneeEmailAddress") or "").lower()
            if assignee:
                _ensure_user(assignee)["comments_assigned_to"] += 1

            for reply in comment.get("replies", []):
                reply_author = reply.get("author", {}).get("emailAddress", "").lower()
                if reply_author:
                    _ensure_user(reply_author)["replies_authored"] += 1
                    if reply.get("action") == "resolve":
                        _ensure_user(reply_author)["comments_resolved"] += 1

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return per_user


# ---------------------------------------------------------------------------
# Event Generation
# ---------------------------------------------------------------------------


def _event_type_for_file(file_info: dict) -> str:
    """Determine the event type based on file type and creation status."""
    mime_short = file_info["mime_short"]
    created = file_info.get("created_in_quarter", False)

    type_map = {
        ("doc", True): "gdrive_doc_created",
        ("doc", False): "gdrive_doc_contributed",
        ("sheet", True): "gdrive_sheet_created",
        ("sheet", False): "gdrive_sheet_contributed",
        ("slides", True): "gdrive_slides_created",
        ("slides", False): "gdrive_slides_contributed",
    }
    return type_map.get((mime_short, created), f"gdrive_{mime_short}_contributed")


_CLASSIFICATION_BOOST_TEXT = {
    "presentation": "presentation slides deck demo talk sprint demo show and tell",
    "architecture_doc": "architecture design review adr rfc documentation",
    "operational_doc": "runbook documentation guide operations",
    "planning_doc": "planning roadmap sprint strategy documentation",
    "process_doc": "retrospective retro process improvement",
    "mentorship_doc": "mentor onboard training knowledge share documentation",
    "status_doc": "status report documentation meeting notes",
    "planning_sheet": "planning tracker spreadsheet",
    "customer_doc": "customer stakeholder feedback documentation",
    "research_doc": "research poc prototype experiment documentation",
    "general_slides": "presentation slides deck",
    "general_sheet": "spreadsheet planning tracker",
    "general_doc": "documentation document",
}


def _build_classification_text(file_info: dict) -> str:
    """Build the text used for competency phrase/keyword matching.

    Includes the filename, MIME type label, classification, description,
    and boosted keywords based on the classification type so that the
    scorer's min_signals threshold (typically 3) can be met.
    """
    classification = file_info.get("classification", "")
    parts = [
        file_info["name"],
        MIME_TYPE_LABELS.get(file_info["mime_short"], ""),
        classification,
        file_info.get("description", ""),
        _CLASSIFICATION_BOOST_TEXT.get(classification, ""),
    ]
    return " ".join(p for p in parts if p)


_COMMENT_ACTIVITY_BOOST_TEXT = "review feedback comments collaboration discussion"


def _has_comment_activity(cmt: dict) -> bool:
    """Return True if the user had any meaningful comment interaction."""
    return (
        cmt.get("comments_authored", 0)
        + cmt.get("replies_authored", 0)
        + cmt.get("comments_resolved", 0)
        + cmt.get("comments_mentioned_in", 0)
        + cmt.get("comments_assigned_to", 0)
    ) > 0


def generate_events(
    files: list[dict],
    user_email: str,
    revision_stats: dict[str, dict] | None = None,
    comment_stats: dict[str, dict] | None = None,
) -> list[dict]:
    """Convert discovered files into events compatible with the collector pipeline.

    Each event follows the structure expected by collector.py's _enrich_event().
    When comment_stats are provided, comment counts are merged into each event
    and comment-related keywords are appended to the classification text.
    """
    events = []
    rev_stats = revision_stats or {}
    cmt_stats = comment_stats or {}

    for f in files:
        event_type = _event_type_for_file(f)

        timestamp = f.get("modified_by_me_time") or f.get("modified_time", "")
        if f.get("created_in_quarter"):
            timestamp = f.get("created_time") or timestamp

        event_id = f"gdrive:{f['id']}:{event_type}"

        rev = rev_stats.get(f["id"], {})
        rev_count = rev.get("user_revisions_in_quarter", 0)

        cmt = cmt_stats.get(f["id"], {})

        role = "owner" if f.get("is_owner") else "contributor"

        classification_text = _build_classification_text(f)
        if _has_comment_activity(cmt):
            classification_text += " " + _COMMENT_ACTIVITY_BOOST_TEXT

        event = {
            "id": event_id,
            "source": "gdrive",
            "type": event_type,
            "item_id": f["id"],
            "title": f"[{MIME_TYPE_LABELS.get(f['mime_short'], 'GDrive')}] {f['name']}",
            "timestamp": timestamp,
            "gdrive_role": role,
            "gdrive_classification": f.get("classification", ""),
            "gdrive_competencies": f.get("competencies", []),
            "gdrive_url": f.get("url", ""),
            "gdrive_mime_short": f.get("mime_short", ""),
            "gdrive_revision_count": rev_count,
            "gdrive_created_in_quarter": f.get("created_in_quarter", False),
            "gdrive_comments_authored": cmt.get("comments_authored", 0),
            "gdrive_replies_authored": cmt.get("replies_authored", 0),
            "gdrive_comments_resolved": cmt.get("comments_resolved", 0),
            "gdrive_comments_mentioned_in": cmt.get("comments_mentioned_in", 0),
            "gdrive_comments_assigned_to": cmt.get("comments_assigned_to", 0),
            "extra_classification_text": classification_text,
        }
        events.append(event)

    return events


def generate_comment_only_events(
    service,
    user_email: str,
    quarter_start: str,
    quarter_end: str | None = None,
    existing_file_ids: set[str] | None = None,
    max_files: int = 50,
) -> list[dict]:
    """Generate events for files where the user only commented (no edits).

    Discovers files the user can access that have comments in the quarter,
    then filters to files NOT already captured by discover_files(). This
    captures "review-only" contributions from users who commented but
    never edited the file content.
    """
    existing = existing_file_ids or set()
    user_lower = user_email.lower()

    mime_filter = " or ".join(f"mimeType='{m}'" for m in GOOGLE_MIME_TYPES)
    q = (
        f"({mime_filter})"
        f" and modifiedTime >= '{quarter_start}'"
        f" and trashed = false"
    )
    if quarter_end:
        q += f" and modifiedTime < '{quarter_end}'"

    fields = (
        "nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, "
        "webViewLink, description)"
    )

    events: list[dict] = []
    page_token = None
    files_checked = 0

    while files_checked < max_files:
        try:
            resp = _api_call_with_backoff(
                lambda pt=page_token: service.files()
                .list(
                    q=q,
                    fields=fields,
                    pageSize=100,
                    orderBy="modifiedTime desc",
                    pageToken=pt,
                )
                .execute()
            )
        except Exception as e:
            logger.debug("Comment-only file discovery failed: %s", e)
            break

        raw_files = resp.get("files", [])
        if not raw_files:
            break

        for f in raw_files:
            if f["id"] in existing:
                continue
            if files_checked >= max_files:
                break
            files_checked += 1

            cmt = get_comment_stats(service, f["id"], user_lower, quarter_start)
            if not _has_comment_activity(cmt):
                continue

            mime = f.get("mimeType", "")
            mime_short = GOOGLE_MIME_TYPES.get(mime, "unknown")
            classification, competencies = classify_filename(f["name"], mime_short)

            event_type = f"gdrive_{mime_short}_commented"
            event_id = f"gdrive:{f['id']}:{event_type}"

            file_info_for_text = {
                "name": f["name"],
                "mime_short": mime_short,
                "classification": classification,
                "description": f.get("description", ""),
            }
            classification_text = (
                _build_classification_text(file_info_for_text)
                + " "
                + _COMMENT_ACTIVITY_BOOST_TEXT
            )

            event = {
                "id": event_id,
                "source": "gdrive",
                "type": event_type,
                "item_id": f["id"],
                "title": f"[{MIME_TYPE_LABELS.get(mime_short, 'GDrive')}] {f['name']}",
                "timestamp": f.get("modifiedTime", ""),
                "gdrive_role": "commenter",
                "gdrive_classification": classification,
                "gdrive_competencies": competencies,
                "gdrive_url": f.get("webViewLink", ""),
                "gdrive_mime_short": mime_short,
                "gdrive_revision_count": 0,
                "gdrive_created_in_quarter": False,
                "gdrive_comments_authored": cmt.get("comments_authored", 0),
                "gdrive_replies_authored": cmt.get("replies_authored", 0),
                "gdrive_comments_resolved": cmt.get("comments_resolved", 0),
                "gdrive_comments_mentioned_in": cmt.get("comments_mentioned_in", 0),
                "gdrive_comments_assigned_to": cmt.get("comments_assigned_to", 0),
                "extra_classification_text": classification_text,
            }
            events.append(event)

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    if events:
        logger.info(
            "GDrive comment-only events: %d files checked, %d comment-only events",
            files_checked,
            len(events),
        )
    return events


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

CACHE_FILENAME = "gdrive_contributions_cache.json"


def _cache_path(perf_dir: Path) -> Path:
    return perf_dir / CACHE_FILENAME


def load_cache(perf_dir: Path) -> dict | None:
    """Load cached GDrive contributions for the quarter."""
    path = _cache_path(perf_dir)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cached_at = data.get("cached_at", "")
        if cached_at:
            cached_dt = datetime.fromisoformat(cached_at)
            age_hours = (datetime.now() - cached_dt).total_seconds() / 3600
            if age_hours > 24:
                logger.info("GDrive cache expired (%.1f hours old)", age_hours)
                return None
        return data
    except Exception as e:
        logger.debug("Failed to load GDrive cache: %s", e)
        return None


def save_cache(
    perf_dir: Path,
    files: list[dict],
    events: list[dict],
    comment_stats: dict[str, dict] | None = None,
) -> None:
    """Save GDrive contributions to quarterly cache."""
    perf_dir.mkdir(parents=True, exist_ok=True)
    cache_data = {
        "files": files,
        "events": events,
        "file_count": len(files),
        "event_count": len(events),
        "comment_stats": comment_stats or {},
        "cached_at": datetime.now().isoformat(),
    }
    try:
        with open(_cache_path(perf_dir), "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
        logger.info("GDrive cache saved: %d files, %d events", len(files), len(events))
    except Exception as e:
        logger.warning("Failed to save GDrive cache: %s", e)


# ---------------------------------------------------------------------------
# Main Collection Entry Point
# ---------------------------------------------------------------------------


def collect_gdrive_contributions(
    perf_dir: Path,
    target: date,
    user_email: str | None = None,
    force_refresh: bool = False,
    include_revisions: bool = True,
    max_revision_files: int = 30,
    include_comments: bool = True,
    max_comment_files: int = 30,
) -> list[dict]:
    """Collect Google Drive contribution events for the current quarter.

    This is the main entry point called from collector.py.

    Args:
        perf_dir: Performance data directory for the quarter.
        target: The date being collected for (used for quarter calculation).
        user_email: The user's email. If None, detected from Drive API.
        force_refresh: If True, bypass the cache.
        include_revisions: If True, fetch revision stats per file.
        max_revision_files: Max files to fetch revisions for (rate limit protection).
        include_comments: If True, fetch comment stats per file.
        max_comment_files: Max files to fetch comments for (rate limit protection).

    Returns:
        List of event dicts compatible with collector.py's event pipeline.
    """
    if not force_refresh:
        cached = load_cache(perf_dir)
        if cached:
            logger.info(
                "Using cached GDrive contributions: %d events",
                cached.get("event_count", 0),
            )
            return cached.get("events", [])

    try:
        from tool_modules.aa_gdrive.src.tools_basic import get_drive_service
    except ImportError:
        logger.warning("Google Drive module not available")
        return []

    service, error = get_drive_service()
    if error:
        logger.warning("Google Drive not authenticated: %s", error)
        return []

    if not user_email:
        try:
            about = service.about().get(fields="user").execute()
            user_email = about.get("user", {}).get("emailAddress", "")
        except Exception as e:
            logger.warning("Failed to get user email from Drive: %s", e)
            return []

    if not user_email:
        logger.warning("No user email available for GDrive collection")
        return []

    year = target.year
    quarter = (target.month - 1) // 3 + 1
    quarter_starts = QUARTER_STARTS
    m, d = quarter_starts[quarter]
    quarter_start = date(year, m, d).isoformat() + "T00:00:00Z"

    next_q = quarter + 1
    if next_q > 4:
        next_q = 1
        year += 1
    nm, nd = quarter_starts[next_q]
    quarter_end = date(year, nm, nd).isoformat() + "T00:00:00Z"

    files = discover_files(service, user_email, quarter_start, quarter_end)

    revision_stats: dict[str, dict] = {}
    if include_revisions and files:
        candidates = [f for f in files if f.get("role") in ("owner", "contributor")][
            :max_revision_files
        ]

        for f in candidates:
            stats = get_revision_stats(service, f["id"], user_email, quarter_start)
            revision_stats[f["id"]] = stats

    comment_stats: dict[str, dict] = {}
    if include_comments and files:
        candidates = [f for f in files if f.get("role") in ("owner", "contributor")][
            :max_comment_files
        ]

        for f in candidates:
            stats = get_comment_stats(service, f["id"], user_email, quarter_start)
            if stats.get("total_comments", 0) > 0:
                comment_stats[f["id"]] = stats

    events = generate_events(files, user_email, revision_stats, comment_stats)

    if include_comments:
        existing_file_ids = {f["id"] for f in files}
        comment_only = generate_comment_only_events(
            service,
            user_email,
            quarter_start,
            quarter_end,
            existing_file_ids=existing_file_ids,
            max_files=max_comment_files,
        )
        events.extend(comment_only)

    save_cache(perf_dir, files, events, comment_stats)

    logger.info(
        "GDrive collection complete: %d files -> %d events "
        "(revisions checked: %d, comments checked: %d)",
        len(files),
        len(events),
        len(revision_stats),
        len(comment_stats),
    )
    return events


# ---------------------------------------------------------------------------
# Shared Drive (Team Drive) Support for Peer Data Capture
# ---------------------------------------------------------------------------

SHARED_DRIVE_CACHE_FILENAME = "gdrive_shared_drive_cache.json"
SHARED_DRIVE_INDEX_FILENAME = "gdrive_shared_drive_user_index.json"


def _shared_drive_cache_path(perf_dir: Path) -> Path:
    return perf_dir / SHARED_DRIVE_CACHE_FILENAME


def _shared_drive_index_path(perf_dir: Path) -> Path:
    return perf_dir / SHARED_DRIVE_INDEX_FILENAME


def load_shared_drive_cache(perf_dir: Path) -> dict | None:
    """Load cached shared drive file+revision data for the quarter."""
    path = _shared_drive_cache_path(perf_dir)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cached_at = data.get("cached_at", "")
        if cached_at:
            cached_dt = datetime.fromisoformat(cached_at)
            age_hours = (datetime.now() - cached_dt).total_seconds() / 3600
            if age_hours > 24:
                logger.info("Shared drive cache expired (%.1f hours old)", age_hours)
                return None
        return data
    except Exception as e:
        logger.debug("Failed to load shared drive cache: %s", e)
        return None


def save_shared_drive_cache(
    perf_dir: Path,
    files: list[dict],
    user_index: dict[str, list[dict]],
) -> None:
    """Save shared drive files and per-user index to cache."""
    perf_dir.mkdir(parents=True, exist_ok=True)
    cache_data = {
        "files": files,
        "file_count": len(files),
        "user_count": len(user_index),
        "cached_at": datetime.now().isoformat(),
    }
    try:
        with open(_shared_drive_cache_path(perf_dir), "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
        with open(_shared_drive_index_path(perf_dir), "w", encoding="utf-8") as f:
            json.dump(user_index, f, indent=2)
        logger.info(
            "Shared drive cache saved: %d files, %d users indexed",
            len(files),
            len(user_index),
        )
    except Exception as e:
        logger.warning("Failed to save shared drive cache: %s", e)


def load_shared_drive_user_index(perf_dir: Path) -> dict[str, list[dict]] | None:
    """Load the per-user shared drive index (email -> file contribution list)."""
    path = _shared_drive_index_path(perf_dir)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.debug("Failed to load shared drive user index: %s", e)
        return None


def discover_shared_drive_files(
    service,
    drive_id: str,
    quarter_start: str,
    quarter_end: str | None = None,
) -> list[dict]:
    """Discover all Docs/Sheets/Slides on a Shared Drive modified this quarter.

    Unlike personal discovery, this returns ALL files (not filtered to one user)
    since we need to build a per-user index from revision history.
    """
    mime_filter = " or ".join(f"mimeType='{m}'" for m in GOOGLE_MIME_TYPES)
    q = (
        f"({mime_filter})"
        f" and modifiedTime >= '{quarter_start}'"
        f" and trashed = false"
    )
    if quarter_end:
        q += f" and modifiedTime < '{quarter_end}'"

    fields = (
        "nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, "
        "lastModifyingUser, webViewLink, description)"
    )

    all_files: list[dict] = []
    page_token = None

    while True:
        resp = _api_call_with_backoff(
            lambda pt=page_token: service.files()
            .list(
                q=q,
                fields=fields,
                pageSize=500,
                orderBy="modifiedTime desc",
                pageToken=pt,
                corpora="drive",
                driveId=drive_id,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            )
            .execute()
        )
        raw_files = resp.get("files", [])
        for f in raw_files:
            mime = f.get("mimeType", "")
            mime_short = GOOGLE_MIME_TYPES.get(mime, "unknown")
            classification, competencies = classify_filename(f["name"], mime_short)

            last_modifier = (
                f.get("lastModifyingUser", {}).get("emailAddress", "").lower()
            )

            all_files.append(
                {
                    "id": f["id"],
                    "name": f["name"],
                    "mime_type": mime,
                    "mime_short": mime_short,
                    "created_time": f.get("createdTime", ""),
                    "modified_time": f.get("modifiedTime", ""),
                    "url": f.get("webViewLink", ""),
                    "last_modifier": last_modifier,
                    "classification": classification,
                    "competencies": competencies,
                    "description": f.get("description", ""),
                    "shared_drive_id": drive_id,
                }
            )

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    logger.info(
        "Shared drive %s: discovered %d files modified since %s",
        drive_id,
        len(all_files),
        quarter_start[:10],
    )
    return all_files


def build_user_index_from_revisions(
    service,
    files: list[dict],
    quarter_start: str,
    max_files: int = 100,
    include_comments: bool = True,
) -> dict[str, list[dict]]:
    """Build per-user attribution index from revision and comment history.

    Returns: {email: [{file_id, file_name, revision_count, comment_stats, ...}, ...]}

    This is the core of peer attribution -- for each file, we check who
    made revisions and comments in the quarter and record their contribution.
    Comment-only contributors (no edits) are also included when they have
    meaningful comment activity.
    """
    user_index: dict[str, list[dict]] = {}

    try:
        qs_dt = datetime.fromisoformat(quarter_start.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        qs_dt = datetime(2026, 1, 1)

    checked = 0
    skipped = 0
    for f in files[:max_files]:
        try:
            resp = _api_call_with_backoff(
                lambda fid=f["id"]: service.revisions()
                .list(
                    fileId=fid,
                    fields="revisions(id, modifiedTime, lastModifyingUser)",
                    pageSize=200,
                )
                .execute()
            )
        except Exception as e:
            logger.debug("Revisions failed for %s: %s", f["id"], e)
            skipped += 1
            continue

        checked += 1
        revisions = resp.get("revisions", [])

        user_revs: dict[str, list[str]] = {}
        for rev in revisions:
            rev_email = rev.get("lastModifyingUser", {}).get("emailAddress", "").lower()
            rev_time = rev.get("modifiedTime", "")
            if not rev_email or not rev_time:
                continue

            try:
                rev_dt = datetime.fromisoformat(rev_time.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            if rev_dt >= qs_dt:
                user_revs.setdefault(rev_email, []).append(rev_time)

        per_user_comments: dict[str, dict] = {}
        if include_comments:
            per_user_comments = get_file_comment_stats_for_all_users(
                service, f["id"], quarter_start
            )

        all_emails = set(user_revs.keys()) | set(per_user_comments.keys())

        for email in all_emails:
            rev_times = user_revs.get(email, [])
            cmt = per_user_comments.get(email, {})

            entry = {
                "file_id": f["id"],
                "file_name": f["name"],
                "mime_short": f["mime_short"],
                "classification": f["classification"],
                "competencies": f["competencies"],
                "url": f.get("url", ""),
                "description": f.get("description", ""),
                "revision_count": len(rev_times),
                "first_revision": min(rev_times) if rev_times else None,
                "last_revision": max(rev_times) if rev_times else None,
                "created_time": f.get("created_time", ""),
                "modified_time": f.get("modified_time", ""),
                "comments_authored": cmt.get("comments_authored", 0),
                "replies_authored": cmt.get("replies_authored", 0),
                "comments_resolved": cmt.get("comments_resolved", 0),
                "comments_mentioned_in": cmt.get("comments_mentioned_in", 0),
                "comments_assigned_to": cmt.get("comments_assigned_to", 0),
            }
            user_index.setdefault(email, []).append(entry)

    logger.info(
        "Shared drive user index: %d files checked (%d skipped), %d unique users found",
        checked,
        skipped,
        len(user_index),
    )
    return user_index


def generate_peer_events_from_index(
    peer_email: str,
    user_index: dict[str, list[dict]],
    quarter_start: str,
) -> list[dict]:
    """Generate QC events for a specific peer from the shared drive user index.

    Filters the pre-built index to the peer's email and produces events
    in the same format as generate_events() for the collector pipeline.
    Comment-only contributors get a gdrive_*_commented event type.
    """
    peer_lower = peer_email.lower()
    contributions = user_index.get(peer_lower, [])
    if not contributions:
        return []

    try:
        qs_date = datetime.fromisoformat(quarter_start.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        qs_date = date(2026, 1, 1)

    events = []
    for c in contributions:
        mime_short = c.get("mime_short", "doc")
        created_time = c.get("created_time", "")

        created_in_quarter = False
        if created_time:
            try:
                ct = datetime.fromisoformat(created_time.replace("Z", "+00:00")).date()
                created_in_quarter = ct >= qs_date
            except (ValueError, TypeError):
                pass

        rev_count = c.get("revision_count", 0)
        cmt = {
            "comments_authored": c.get("comments_authored", 0),
            "replies_authored": c.get("replies_authored", 0),
            "comments_resolved": c.get("comments_resolved", 0),
            "comments_mentioned_in": c.get("comments_mentioned_in", 0),
            "comments_assigned_to": c.get("comments_assigned_to", 0),
        }
        has_comments = _has_comment_activity(cmt)

        if rev_count > 0:
            file_info = {
                "mime_short": mime_short,
                "created_in_quarter": created_in_quarter,
            }
            event_type = _event_type_for_file(file_info)
            role = "contributor"
        elif has_comments:
            event_type = f"gdrive_{mime_short}_commented"
            role = "commenter"
        else:
            continue

        timestamp = c.get("last_revision") or c.get("modified_time", "")

        event_id = f"gdrive_shared:{c['file_id']}:{peer_lower}:{event_type}"

        classification = c.get("classification", f"general_{mime_short}")
        file_info_for_text = {
            "name": c["file_name"],
            "mime_short": mime_short,
            "classification": classification,
            "description": c.get("description", ""),
        }
        classification_text = _build_classification_text(file_info_for_text)
        if has_comments:
            classification_text += " " + _COMMENT_ACTIVITY_BOOST_TEXT

        event = {
            "id": event_id,
            "source": "gdrive",
            "type": event_type,
            "item_id": c["file_id"],
            "title": f"[{MIME_TYPE_LABELS.get(mime_short, 'GDrive')}] {c['file_name']}",
            "timestamp": timestamp,
            "gdrive_role": role,
            "gdrive_classification": classification,
            "gdrive_competencies": c.get("competencies", []),
            "gdrive_url": c.get("url", ""),
            "gdrive_mime_short": mime_short,
            "gdrive_revision_count": rev_count,
            "gdrive_created_in_quarter": created_in_quarter,
            "gdrive_shared_drive": True,
            "gdrive_comments_authored": cmt.get("comments_authored", 0),
            "gdrive_replies_authored": cmt.get("replies_authored", 0),
            "gdrive_comments_resolved": cmt.get("comments_resolved", 0),
            "gdrive_comments_mentioned_in": cmt.get("comments_mentioned_in", 0),
            "gdrive_comments_assigned_to": cmt.get("comments_assigned_to", 0),
            "extra_classification_text": classification_text,
        }
        events.append(event)

    logger.info(
        "Shared drive peer events for %s: %d events from %d file contributions",
        peer_email,
        len(events),
        len(contributions),
    )
    return events


def ensure_shared_drive_index(
    perf_dir: Path,
    drive_ids: list[str],
    target: date,
    force_refresh: bool = False,
    max_revision_files: int = 100,
) -> dict[str, list[dict]]:
    """Ensure the shared drive user index is built and cached.

    Called once before iterating over peers. Subsequent peer calls just read
    the cached index and filter by email.

    Args:
        perf_dir: Quarter performance directory.
        drive_ids: List of Shared Drive IDs to index.
        target: Date used for quarter calculation.
        force_refresh: Bypass cache.
        max_revision_files: Max files to fetch revisions for per drive.

    Returns:
        Per-user index: {email: [contribution_entries]}
    """
    if not force_refresh:
        cache = load_shared_drive_cache(perf_dir)
        if cache:
            index = load_shared_drive_user_index(perf_dir)
            if index is not None:
                logger.info(
                    "Using cached shared drive index: %d users",
                    len(index),
                )
                return index

    try:
        from tool_modules.aa_gdrive.src.tools_basic import get_drive_service
    except ImportError:
        logger.warning("Google Drive module not available")
        return {}

    service, error = get_drive_service()
    if error:
        logger.warning("Google Drive not authenticated: %s", error)
        return {}

    year = target.year
    quarter = (target.month - 1) // 3 + 1
    quarter_starts = QUARTER_STARTS
    m, d = quarter_starts[quarter]
    quarter_start = date(year, m, d).isoformat() + "T00:00:00Z"

    next_q = quarter + 1
    if next_q > 4:
        next_q = 1
        year += 1
    nm, nd = quarter_starts[next_q]
    quarter_end = date(year, nm, nd).isoformat() + "T00:00:00Z"

    all_files: list[dict] = []
    combined_index: dict[str, list[dict]] = {}

    for drive_id in drive_ids:
        try:
            files = discover_shared_drive_files(
                service, drive_id, quarter_start, quarter_end
            )
            all_files.extend(files)

            index = build_user_index_from_revisions(
                service,
                files,
                quarter_start,
                max_files=max_revision_files,
            )
            for email, entries in index.items():
                combined_index.setdefault(email, []).extend(entries)

        except Exception as e:
            logger.warning("Failed to index shared drive %s: %s", drive_id, e)

    save_shared_drive_cache(perf_dir, all_files, combined_index)

    logger.info(
        "Shared drive index built: %d files across %d drives, %d unique users",
        len(all_files),
        len(drive_ids),
        len(combined_index),
    )
    return combined_index


def collect_shared_drive_peer_contributions(
    perf_dir: Path,
    peer_email: str,
    target: date,
    drive_ids: list[str] | None = None,
    force_refresh: bool = False,
) -> list[dict]:
    """Collect GDrive contribution events for a peer from shared drives.

    Loads the pre-built user index (or builds it on first call) and filters
    to the specific peer's email.

    Args:
        perf_dir: Quarter performance directory.
        peer_email: The peer's email address (e.g. "jsmith@redhat.com").
        target: Date for quarter calculation.
        drive_ids: Shared Drive IDs. If None, reads from config.json.
        force_refresh: Bypass cache.

    Returns:
        List of event dicts for the peer, compatible with collector.py.
    """
    if not drive_ids:
        drive_ids = _get_shared_drive_ids()
    if not drive_ids:
        return []

    user_index = ensure_shared_drive_index(
        perf_dir,
        drive_ids,
        target,
        force_refresh=force_refresh,
    )
    if not user_index:
        return []

    year = target.year
    quarter = (target.month - 1) // 3 + 1
    quarter_starts = QUARTER_STARTS
    m, d = quarter_starts[quarter]
    quarter_start = date(year, m, d).isoformat() + "T00:00:00Z"

    return generate_peer_events_from_index(peer_email, user_index, quarter_start)


def _get_shared_drive_ids() -> list[str]:
    """Read shared drive IDs from config.json."""
    try:
        config_path = Path(__file__).resolve().parent.parent.parent / "config.json"
        if not config_path.exists():
            return []
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        drives = config.get("google", {}).get("shared_drives", [])
        return [d["id"] for d in drives if d.get("id")]
    except Exception as e:
        logger.debug("Failed to read shared drive config: %s", e)
        return []


def discover_all_shared_drives(service=None) -> list[dict]:
    """List all Shared Drives the authenticated user has access to.

    Useful for auditing coverage -- compare this list against the
    configured shared_drives in config.json to find drives that
    peers may use but are not yet indexed for QC scoring.
    """
    if service is None:
        try:
            from tool_modules.aa_gdrive.src.tools_basic import get_drive_service

            service, error = get_drive_service()
            if error:
                logger.warning("Drive not authenticated: %s", error)
                return []
        except ImportError:
            logger.warning("Google Drive module not available")
            return []

    drives: list[dict] = []
    page_token = None

    while True:
        try:
            kwargs: dict = {
                "pageSize": 100,
                "fields": "nextPageToken, drives(id, name, createdTime)",
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = service.drives().list(**kwargs).execute()
            for d in resp.get("drives", []):
                drives.append(
                    {
                        "id": d["id"],
                        "name": d.get("name", ""),
                        "created": d.get("createdTime", "")[:10],
                    }
                )
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        except Exception as e:
            logger.warning("Failed to list shared drives: %s", e)
            break

    configured = set(_get_shared_drive_ids())
    for d in drives:
        d["configured"] = d["id"] in configured

    logger.info(
        "Discovered %d shared drives (%d configured)",
        len(drives),
        sum(1 for d in drives if d["configured"]),
    )
    return drives
